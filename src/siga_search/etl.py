"""ETL: lê os CSVs do SIGA (ISO-8859-1) e popula o SQLite.

As colunas são lidas pelo nome do header, então o mesmo código carrega o layout
antigo (sem ID Forn) e o novo. Coluna obrigatória ausente ou CSV ausente => exit 1.

Uso:
    python -m siga_search.etl [--db data/siga.db] [--csv-dir data/csv] [--only TABELA]
"""
from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from .normalize import (
    chave_fornecedor,
    eh_cnpj,
    nome_norm,
    parse_date,
    parse_decimal,
    parse_int,
    processo_norm,
    s,
    sem_acento,
)

ENCODING = "iso-8859-1"
BATCH = 5000

# Aumenta o limite do csv para descrições muito longas
csv.field_size_limit(10 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------

@dataclass
class Spec:
    csv: str
    tabela: str
    colunas: list[str]                 # colunas SQL, na ordem da tupla do transform
    transform: Callable[[dict[str, str]], tuple | None]
    campos: dict[str, str]             # apelido -> nome no header (obrigatórias)
    opcionais: dict[str, str] = field(default_factory=dict)  # ausentes viram ""
    ignoradas: tuple[str, ...] = ()    # colunas conhecidas que não são carregadas
    sem_nome: str | None = None        # apelido da 1ª coluna sem nome no fim do header
    dedup: bool = False                # desfaz a repetição por processo da ata (1ª coluna = id_ata)


def _norm_col(h: str) -> str:
    # BOM (como caractere ou como bytes UTF-8 lidos em latin-1) e aspas
    h = h.replace("\ufeff", "").replace("\xef\xbb\xbf", "").replace('"', "")
    return " ".join(sem_acento(h).casefold().split())


def _cabecalho(header: list[str], spec: Spec) -> tuple[dict[str, int], list[str], list[str]]:
    """Posição de cada apelido, obrigatórias ausentes e colunas desconhecidas."""
    nomes = [_norm_col(h) for h in header]
    while nomes and not nomes[-1]:
        nomes.pop()
    pos = {n: i for i, n in enumerate(nomes)}
    idx: dict[str, int] = {}
    faltando = []
    for apelido, nome in spec.campos.items():
        if _norm_col(nome) in pos:
            idx[apelido] = pos[_norm_col(nome)]
        else:
            faltando.append(nome)
    for apelido, nome in spec.opcionais.items():
        if _norm_col(nome) in pos:
            idx[apelido] = pos[_norm_col(nome)]
    if spec.sem_nome and spec.sem_nome not in idx:
        idx[spec.sem_nome] = len(nomes)
    conhecidas = {_norm_col(n) for n in
                  [*spec.campos.values(), *spec.opcionais.values(), *spec.ignoradas]}
    desconhecidas = [h.strip() or "(sem nome)" for h, n in zip(header, nomes)
                     if n not in conhecidas]
    return idx, faltando, desconhecidas


def _ler_header(path: Path) -> list[str]:
    with path.open("r", encoding=ENCODING, newline="") as f:
        return next(csv.reader(f, delimiter=";"), [])


def _linhas(path: Path, spec: Spec) -> Iterator[tuple[int, dict[str, str]]]:
    """(nº da linha, {apelido: texto}); opcionais ausentes e campos faltando viram ""."""
    with path.open("r", encoding=ENCODING, newline="") as f:
        reader = csv.reader(f, delimiter=";")
        idx, _, _ = _cabecalho(next(reader, []), spec)
        apelidos = list(idx)
        posicoes = [idx[a] for a in apelidos]
        largura = max(posicoes) + 1
        ausentes = {a: "" for a in spec.opcionais if a not in idx}
        for linha, row in enumerate(reader, start=2):
            if len(row) < largura:
                row += [""] * (largura - len(row))
            r = dict(zip(apelidos, [row[i] for i in posicoes]))
            if ausentes:
                r.update(ausentes)
            yield linha, r


# ---------------------------------------------------------------------------
# Fornecedores: mapas para ligar tabelas que não trazem CPF/CNPJ (via ID Forn)
# ou que trazem documento mascarado sem ID Forn (via documento + nome).
# ---------------------------------------------------------------------------

_CHAVE_POR_ID: dict[int, str] = {}
_CHAVES_POR_NOME: dict[tuple[str, str], set[str]] = {}


def _ler_fornecedores(path: Path) -> None:
    _CHAVE_POR_ID.clear()
    _CHAVES_POR_NOME.clear()
    _chave_por_nome.cache_clear()
    for _, r in _linhas(path, _FORNECEDORES):
        id_forn = parse_int(r["id_forn"])
        chave = chave_fornecedor(r["cpf_cnpj"], id_forn)
        if not chave:
            continue
        if id_forn is not None:
            _CHAVE_POR_ID[id_forn] = chave
        digits = re.sub(r"\D", "", r["cpf_cnpj"])
        _CHAVES_POR_NOME.setdefault((digits, nome_norm(r["nome"])), set()).add(chave)


def _chave_por_id(v: str) -> str | None:
    id_forn = parse_int(v)
    return _CHAVE_POR_ID.get(id_forn) if id_forn is not None else None


@cache
def _chave_por_nome(doc: str, nome: str) -> str | None:
    """CNPJ => dígitos. Documento mascarado => fornecedor com mesmo documento e nome,
    só se for exatamente um."""
    digits = re.sub(r"\D", "", doc)
    if eh_cnpj(digits):
        return digits
    chaves = _CHAVES_POR_NOME.get((digits, nome_norm(nome)))
    if chaves and len(chaves) == 1:
        return next(iter(chaves))
    return None


_LINHAS_POR_ATA: Counter[int] = Counter()


def _ler_atas(path: Path) -> None:
    """Nº de linhas (processos) de cada ata em ATA_REGISTRO_PRECO.CSV."""
    _LINHAS_POR_ATA.clear()
    for _, r in _linhas(path, _ATAS):
        id_ata = parse_int(r["id_ata"])
        if id_ata is not None:
            _LINHAS_POR_ATA[id_ata] += 1


def _chave(r: dict[str, str]) -> str | None:
    """Chave pelo documento/ID Forn da linha. Sem CNPJ na linha, usa a chave que o ID Forn
    tem em fornecedores."""
    id_forn = parse_int(r["id_forn"])
    chave = chave_fornecedor(r["cpf_cnpj"], id_forn)
    if id_forn is not None and chave == f"F{id_forn}":
        return _CHAVE_POR_ID.get(id_forn, chave)
    return chave


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------

def _load(conn: sqlite3.Connection, spec: Spec, csv_path: Path) -> int:
    placeholders = ",".join("?" * len(spec.colunas))
    sql = (f"INSERT OR IGNORE INTO {spec.tabela} ({', '.join(spec.colunas)}) "
           f"VALUES ({placeholders})")
    t0 = time.time()
    n = inseridas = skipped = repetidas = 0
    erros: Counter[str] = Counter()
    exemplos: dict[str, str] = {}
    vistas: Counter[tuple] = Counter()
    batch: list[tuple] = []
    cur = conn.cursor()

    def gravar() -> None:
        nonlocal n, inseridas
        antes = conn.total_changes
        cur.executemany(sql, batch)
        inseridas += conn.total_changes - antes
        n += len(batch)
        batch.clear()

    for linha, r in _linhas(csv_path, spec):
        try:
            tup = spec.transform(r)
        except Exception as e:  # conta e mostra no fim; não interrompe a carga
            tipo = type(e).__name__
            erros[tipo] += 1
            exemplos.setdefault(tipo, f"linha {linha}: {e}")
            continue
        if tup is None:
            skipped += 1
            continue
        if spec.dedup:
            # A extração repete cada linha n vezes (n = processos da ata): grava 1 a cada n.
            # Linhas iguais e legítimas (k registros) chegam k·n vezes e viram k.
            vistas[tup] += 1
            if (vistas[tup] - 1) % _LINHAS_POR_ATA.get(tup[0], 1):
                repetidas += 1
                continue
        batch.append(tup)
        if len(batch) >= BATCH:
            gravar()
            if n % 100000 == 0:
                print(f"    {spec.tabela}: {n:>10,} linhas em {time.time() - t0:6.1f}s",
                      flush=True)
    if batch:
        gravar()
    conn.commit()

    detalhes = [f"skip={skipped}"]
    if spec.dedup:
        detalhes.append(f"linhas repetidas={repetidas}")
    if n - inseridas:
        detalhes.append(f"ignoradas por chave repetida={n - inseridas}")
    if erros:
        detalhes.append(f"erros={sum(erros.values())}")
    print(f"  ✓ {spec.tabela}: {inseridas:,} linhas ({', '.join(detalhes)}) "
          f"em {time.time() - t0:.1f}s", flush=True)
    for tipo, qtd in erros.items():
        print(f"    ! {qtd} linhas com {tipo}; ex.: {exemplos[tipo]}", file=sys.stderr)
    return inseridas


# ---------------------------------------------------------------------------
# Transforms. Cada um recebe a linha como {apelido: texto} e devolve a tupla
# na ordem de `colunas` ou None pra pular.
# ---------------------------------------------------------------------------

def _catalogo(r: dict[str, str]) -> tuple | None:
    id_item = parse_int(r["id_item"])
    if id_item is None:
        return None
    return (
        id_item, parse_int(r["id_tipo"]), s(r["tipo"]), parse_int(r["id_familia"]),
        s(r["familia"]), parse_int(r["id_classe"]), s(r["classe"]), s(r["id_artigo"]),
        s(r["artigo"]), s(r["cod_item"]), s(r["descricao"]), s(r["sustentavel"]),
        s(r["data_extracao"]),
    )


def _fornecedores(r: dict[str, str]) -> tuple | None:
    chave = _chave(r)
    if not chave:
        return None
    return (
        chave, parse_int(r["id_forn"]), s(r["cpf_cnpj"]), s(r["nome"]), s(r["crc"]),
        s(r["tipo_empresarial"]), s(r["me_epp"]), s(r["situacao"]),
        parse_date(r["data_cadastro"]), s(r["cidade"]), s(r["uf"]), s(r["data_extracao"]),
    )


def _licitacoes(r: dict[str, str]) -> tuple | None:
    id_lic = parse_int(r["id_licitacao"])
    if id_lic is None:
        return None
    return (
        id_lic, s(r["licitacao"]), s(r["unidade"]), s(r["objeto"]), s(r["modalidade"]),
        s(r["criterio_julgamento"]), s(r["srp"]),
        parse_date(r["dt_publicacao"]), parse_date(r["dt_limite_proposta"]),
        parse_date(r["dt_abertura"]), parse_date(r["dt_homologacao"]),
        parse_date(r["dt_adjudicacao"]), s(r["status"]),
        parse_decimal(r["valor_total_homologado"]), parse_decimal(r["valor_total_estimado"]),
        s(r["internacional"]), s(r["processo"]), processo_norm(r["processo"]),
        s(r["regime"]), s(r["data_extracao"]),
    )


def _atas(r: dict[str, str]) -> tuple | None:
    id_ata = parse_int(r["id_ata"])
    if id_ata is None:
        return None
    return (
        id_ata, s(r["numero_ata"]), s(r["unidade_gerenciadora"]), s(r["objeto"]),
        s(r["licitacao_sigla"]), parse_date(r["inicio_validade"]),
        parse_date(r["fim_validade"]), s(r["criterio_julgamento"]),
        s(r["cont_tempo_servico"]), s(r["status_ata"]),
        parse_int(r["id_licitacao"]), parse_int(r["id_processo"]),
        s(r["processo"]), processo_norm(r["processo"]), s(r["data_extracao"]),
    )


def _ata_processos(r: dict[str, str]) -> tuple | None:
    id_ata = parse_int(r["id_ata"])
    pn = processo_norm(r["processo"])
    if id_ata is None or pn is None:
        return None
    return (id_ata, parse_int(r["id_processo"]), s(r["processo"]), pn)


def _contratos(r: dict[str, str]) -> tuple | None:
    codigo = s(r["codigo_contrato"])
    if not codigo:
        return None
    return (
        codigo, parse_int(r["id_processo"]), parse_int(r["id_licitacao"]),
        s(r["contratacao"]), s(r["status_contratacao"]), parse_date(r["dt_contratacao"]),
        s(r["unidade"]), s(r["processo"]), processo_norm(r["processo"]), s(r["objeto"]),
        s(r["tipo_aquisicao"]), s(r["criterio_julgamento"]),
        parse_date(r["dt_inicio_vigencia"]), parse_date(r["dt_fim_vigencia"]),
        s(r["fornecedor"]), s(r["cpf_cnpj"]), _chave(r), parse_int(r["id_forn"]),
        parse_decimal(r["valor_total_contrato"]), parse_decimal(r["valor_total_empenhado"]),
        parse_decimal(r["valor_total_liquidado"]), parse_decimal(r["valor_total_pago"]),
        parse_date(r["dt_public_deorj"]), s(r["regime_juridico"]), s(r["url_pncp"]),
        s(r["data_extracao"]),
    )


def _outras_compras(r: dict[str, str]) -> tuple:
    return (
        parse_int(r["id_processo"]), s(r["unidade"]), s(r["processo"]),
        processo_norm(r["processo"]), s(r["objeto"]), s(r["afastamento"]),
        s(r["enquadramento_legal"]), parse_date(r["dt_aprovacao"]),
        parse_decimal(r["valor_processo"]),
        s(r["cpf_cnpj"]), _chave(r), parse_int(r["id_forn"]), s(r["fornecedor_vencedor"]),
        parse_int(r["id_item"]), s(r["item"]), parse_decimal(r["qtd"]),
        s(r["unidade_medida"]), parse_decimal(r["vl_unitario"]),
        s(r["regime"]), s(r["data_extracao"]),
    )


def _compras_diretas(r: dict[str, str]) -> tuple:
    return (*_outras_compras(r), s(r["ped"]), s(r["temporalidade"]))


def _ped(r: dict[str, str]) -> tuple | None:
    id_ped = parse_int(r["id_ped"])
    if id_ped is None:
        return None
    return (
        id_ped, s(r["processo"]), processo_norm(r["processo"]), parse_int(r["ano_ped"]),
        s(r["status_ped"]), s(r["unidade"]), s(r["nu_pesquisa"]), s(r["objeto"]),
        parse_date(r["inicio_disputa"]), parse_date(r["fim_disputa"]),
        parse_int(r["id_item"]), s(r["item"]), parse_decimal(r["qtd"]),
        s(r["status_item"]), s(r["justificativa"]),
        s(r["fornecedor_vencedor"]), parse_int(r["id_forn"]), _chave_por_id(r["id_forn"]),
        s(r["lances"]), s(r["outras_propostas"]), s(r["data_extracao"]),
    )


def _itens_licitacoes(r: dict[str, str]) -> tuple:
    return (
        parse_int(r["id_licitacao"]), s(r["licitacao"]), s(r["unidade"]),
        s(r["modalidade"]), s(r["itens_lotes"]), parse_int(r["id_item"]),
        s(r["familia"]), s(r["classe"]), s(r["artigo"]), s(r["descricao"]),
        parse_decimal(r["quantidade"]), parse_decimal(r["valor_total_homologado"]),
        parse_decimal(r["taxa_homologada"]), s(r["exclusivo_me_epp"]),
        s(r["situacao_item"]), parse_date(r["dt_homologacao_licit"]), s(r["data_extracao"]),
    )


def _itens_atas(r: dict[str, str]) -> tuple:
    return (
        parse_int(r["id_ata"]), s(r["numero_ata"]), s(r["criterio_julgamento"]),
        parse_int(r["id_item"]), s(r["item"]),
        s(r["fornecedor"]), parse_int(r["id_forn"]), _chave_por_id(r["id_forn"]),
        parse_decimal(r["qtd"]), parse_decimal(r["vl_unitario"]),
        parse_decimal(r["taxa_pct"]), s(r["data_extracao"]),
    )


def _part_atas(r: dict[str, str]) -> tuple:
    return (
        parse_int(r["id_ata"]), s(r["numero_ata"]), s(r["unidade_participante"]),
        s(r["criterio_julgamento"]), s(r["item"]), parse_int(r["id_item"]),
        parse_decimal(r["qtd_demandada"]), parse_decimal(r["qtd_consumida"]),
        parse_decimal(r["valor_demandado"]), parse_decimal(r["valor_consumido"]),
        s(r["data_extracao"]),
    )


def _itens_contratos(r: dict[str, str]) -> tuple:
    return (
        s(r["contratacao"]), parse_int(r["id_ata"]), parse_int(r["id_item"]), s(r["item"]),
        parse_decimal(r["qtd_original"]), parse_decimal(r["vl_unit_original"]),
        parse_decimal(r["total_aditivada_suprimida"]),
        parse_decimal(r["vl_unit_aditivado_suprimido"]),
        s(r["elemento"]), s(r["subelemento"]), s(r["data_extracao"]),
    )


def _participantes(r: dict[str, str]) -> tuple:
    # Linha sem CNPJ vem também sem nome (item fracassado, disputa em andamento): a fonte não
    # identifica o licitante, então fica sem chave (só id_forn).
    chave = _chave(r) if r["cpf_cnpj"].strip() else None
    return (
        parse_int(r["id_lic"]), s(r["nu_lic"]), s(r["sigla"]), s(r["unidade"]),
        s(r["modalidade"]), s(r["exclusivo_mpe"]),
        parse_int(r["id_familia"]), s(r["familia"]), parse_int(r["id_classe"]), s(r["classe"]),
        s(r["id_artigo"]), s(r["artigo"]), parse_int(r["id_item"]), s(r["itens_lotes"]),
        s(r["descricao"]), parse_decimal(r["quantidade"]), s(r["situacao_item"]),
        s(r["fornecedor"]), parse_date(r["data_cadastro"]), s(r["mpe"]),
        s(r["cpf_cnpj"]), chave, parse_int(r["id_forn"]), s(r["fornecedor_vencedor"]),
        parse_decimal(r["valor_unit_ofertado"]), parse_decimal(r["taxa_ofertada"]),
        s(r["data_extracao"]),
    )


def _fmap(r: dict[str, str]) -> tuple:
    return (
        s(r["cpf_cnpj"]), _chave_por_nome(r["cpf_cnpj"], r["nome"]), s(r["nome"]),
        s(r["familia"]), s(r["classe"]), s(r["data_extracao"]),
    )


def _fhc(r: dict[str, str]) -> tuple:
    return (
        s(r["nome"]), s(r["cpf_cnpj"]), _chave_por_nome(r["cpf_cnpj"], r["nome"]),
        s(r["contratacao"]), parse_date(r["dt_contratacao"]),
        s(r["processo"]), processo_norm(r["processo"]), s(r["unidade"]),
        parse_decimal(r["valor_total_contratado"]), parse_decimal(r["valor_total_executado"]),
        s(r["tipo_aquisicao"]), s(r["data_extracao"]),
    )


def _hp_atas(r: dict[str, str]) -> tuple:
    return (
        s(r["tipo"]), s(r["familia"]), s(r["classe"]), s(r["artigo"]),
        parse_int(r["id_item"]), s(r["descricao"]),
        s(r["ata_srp"]), s(r["licitacao"]), s(r["unidade_gestora"]), s(r["fornecedor"]),
        parse_date(r["validade_ata"]), parse_decimal(r["qtd"]),
        parse_decimal(r["vl_unitario"]), s(r["data_extracao"]),
    )


def _hp_cd(r: dict[str, str]) -> tuple:
    return (
        s(r["tipo"]), s(r["familia"]), s(r["classe"]), s(r["artigo"]),
        parse_int(r["id_item"]), s(r["descricao"]),
        parse_int(r["id_processo"]), s(r["processo"]), processo_norm(r["processo"]),
        s(r["tipo_compra"]), s(r["unidade_compradora"]), s(r["fornecedor"]),
        parse_date(r["dt_aprovacao"]),
        parse_decimal(r["qtd"]), parse_decimal(r["vl_unitario"]),
        s(r["contratacao"]), s(r["data_extracao"]),
    )


def _hp_licit(r: dict[str, str]) -> tuple:
    return (
        s(r["tipo"]), s(r["familia"]), s(r["classe"]), s(r["artigo"]),
        parse_int(r["id_item"]), s(r["descricao"]),
        s(r["licitacao"]), s(r["modalidade_compra"]), s(r["unidade_compradora"]),
        s(r["fornecedor"]), parse_date(r["dt_homologacao"]),
        parse_decimal(r["qtd"]), parse_decimal(r["vl_unitario"]),
        s(r["contratacao"]), s(r["data_extracao"]),
    )


def _assapc(r: dict[str, str]) -> tuple:
    return (
        s(r["unidade"]), s(r["processo"]), processo_norm(r["processo"]),
        parse_date(r["dt_criacao_processo"]), s(r["status_processo"]),
        parse_decimal(r["valor_estimado"]),
        s(r["contratacao"]), parse_date(r["dt_criacao_contratacao"]), s(r["status_contrato"]),
        s(r["modalidade"]), parse_decimal(r["vl_total_empenhado"]), s(r["chave_siga"]),
        parse_date(r["dt_criacao_nadsiga"]), parse_date(r["dt_emissao_nadsiga"]),
        parse_int(r["ano"]), s(r["fonte_recurso"]), s(r["natureza"]),
        parse_decimal(r["valor_atual_contrato"]), parse_decimal(r["valor_original"]),
        parse_date(r["data_extracao"]),
    )


def _sancoes(r: dict[str, str]) -> tuple:
    return (
        s(r["nome"]), s(r["cpf_cnpj"]), _chave(r), parse_int(r["id_forn"]),
        s(r["enquadramento_legal"]), s(r["numero_processo"]),
        processo_norm(r["numero_processo"]),
        parse_date(r["dt_efetivacao"]), s(r["prazo"]),
        parse_date(r["dt_inicio"]), parse_date(r["dt_final"]),
        s(r["justificativa"]), s(r["motivo"]), s(r["orgao_apenador"]), s(r["status"]),
        s(r["data_extracao"]),
    )


def _fornecedor_sancoes(r: dict[str, str]) -> tuple:
    return (
        s(r["nome"]), s(r["cpf_cnpj"]), _chave(r), parse_int(r["id_forn"]),
        s(r["orgao_apenador"]), s(r["enquadramento_legal"]), s(r["motivo"]),
        s(r["contrato"]), parse_date(r["dt_efetivacao"]), s(r["status_penalidade"]),
        s(r["data_extracao"]),
    )


# ---------------------------------------------------------------------------
# Specs por tabela. Ordem importa: tabelas-mestre antes das que as referenciam.
# Os nomes de coluna seguem o header do CSV (comparados sem acento/caixa/espaços extras).
# ---------------------------------------------------------------------------

_ID_FORN = {"id_forn": "ID Forn"}

_CAMPOS_COMPRA = {
    "unidade": "Unidade", "id_processo": "ID Processo", "processo": "Processo",
    "objeto": "Objeto", "afastamento": "Afastamento",
    "enquadramento_legal": "Enquadramento Legal", "dt_aprovacao": "Data de Aprovação",
    "valor_processo": "Valor do Processo (R$)", "cpf_cnpj": "CNPJ_CPF",
    "fornecedor_vencedor": "Fornecedor Vencedor", "id_item": "ID Item", "item": "Item",
    "qtd": "Qtd.", "unidade_medida": "Unidade de Medida",
    "vl_unitario": "Vl. Unitário (R$)", "regime": "Regime",
    "data_extracao": "data_extracao",
}
_COLUNAS_COMPRA = [
    "id_processo", "unidade", "processo", "processo_norm", "objeto", "afastamento",
    "enquadramento_legal", "dt_aprovacao", "valor_processo", "cpf_cnpj", "cnpj_norm",
    "id_forn", "fornecedor_vencedor", "id_item", "item", "qtd", "unidade_medida",
    "vl_unitario", "regime", "data_extracao",
]

_CAMPOS_ATA = {
    "id_ata": "ID Ata", "numero_ata": "Número da Ata",
    "unidade_gerenciadora": "Unidade Gerenciadora", "objeto": "Objeto",
    "licitacao_sigla": "Licitação", "inicio_validade": "Início da Validade",
    "fim_validade": "Fim da Validade", "criterio_julgamento": "Critério de Julgamento",
    "cont_tempo_servico": "Cont. Tempo de Serviço", "status_ata": "Status da Ata",
    "id_licitacao": "id licitacao", "id_processo": "id processo", "processo": "processo",
    "data_extracao": "data_extracao",
}

_CAMPOS_PRECO = {
    "tipo": "Tipo", "familia": "Família", "classe": "Classe", "artigo": "Artigo",
    "id_item": "ID Item", "descricao": "Descrição", "fornecedor": "Fornecedor",
    "qtd": "Qtd. Item", "vl_unitario": "Valor Unitário (R$)",
    "data_extracao": "data_extracao",
}

_FORNECEDORES = Spec(
    "FORNECEDORES.CSV", "fornecedores",
    ["cnpj_norm", "id_forn", "cpf_cnpj", "nome", "crc", "tipo_empresarial", "me_epp",
     "situacao", "data_cadastro", "cidade", "uf", "data_extracao"],
    _fornecedores,
    {"nome": "Nome/Razão Social", "cpf_cnpj": "CPF/CNPJ", "crc": "CRC",
     "tipo_empresarial": "Tipo Empresarial", "me_epp": "ME/EPP",
     "situacao": "Situação da Empresa", "data_cadastro": "Data de Cadastro",
     "cidade": "Cidade", "uf": "UF", "data_extracao": "Data_extracao"},
    _ID_FORN,
)

# Uma linha por ata (a 1ª de cada ID Ata); os processos vão todos para ata_processos.
_ATAS = Spec(
    "ATA_REGISTRO_PRECO.CSV", "atas_registro_preco",
    ["id_ata", "numero_ata", "unidade_gerenciadora", "objeto", "licitacao_sigla",
     "inicio_validade", "fim_validade", "criterio_julgamento", "cont_tempo_servico",
     "status_ata", "id_licitacao", "id_processo", "processo", "processo_norm",
     "data_extracao"],
    _atas, _CAMPOS_ATA,
)

SPECS: list[Spec] = [
    Spec(
        "CATALOGO.CSV", "catalogo",
        ["id_item", "id_tipo", "tipo", "id_familia", "familia", "id_classe", "classe",
         "id_artigo", "artigo", "cod_item", "descricao", "sustentavel", "data_extracao"],
        _catalogo,
        {"id_tipo": "ID Tipo", "tipo": "Tipo", "id_familia": "ID Família",
         "familia": "Família", "id_classe": "ID Classe", "classe": "Classe",
         "id_artigo": "ID Artigo", "artigo": "Artigo", "id_item": "ID Item",
         "cod_item": "Cód. Item", "descricao": "Descrição Item",
         "sustentavel": "Sustentável", "data_extracao": "data_extracao"},
    ),
    _FORNECEDORES,
    Spec(
        "LICITACOES.CSV", "licitacoes",
        ["id_licitacao", "licitacao", "unidade", "objeto", "modalidade",
         "criterio_julgamento", "srp", "dt_publicacao", "dt_limite_proposta",
         "dt_abertura", "dt_homologacao", "dt_adjudicacao", "status",
         "valor_total_homologado", "valor_total_estimado", "internacional",
         "processo", "processo_norm", "regime", "data_extracao"],
        _licitacoes,
        {"id_licitacao": "ID Licitação", "licitacao": "Licitação", "unidade": "Unidade",
         "objeto": "Objeto", "modalidade": "Modalidade",
         "criterio_julgamento": "Critério de Julgamento", "srp": "SRP",
         "dt_publicacao": "Data/hora da Publicação",
         "dt_limite_proposta": "Data/Hora Limite de Proposta",
         "dt_abertura": "Data/Hora Abertura de Sessão",
         "dt_homologacao": "Data/Hora Homologação",
         "dt_adjudicacao": "Data/Hora Adjudicação", "status": "Status",
         "valor_total_homologado": "Valor Total Homologado (R$)",
         "valor_total_estimado": "Valor Total Estimado (R$)",
         "internacional": "Internacional", "processo": "Processos", "regime": "Regime",
         "data_extracao": "Data_extracao"},
    ),
    _ATAS,
    Spec(
        "ATA_REGISTRO_PRECO.CSV", "ata_processos",
        ["id_ata", "id_processo", "processo", "processo_norm"],
        _ata_processos, _CAMPOS_ATA,
    ),
    Spec(
        "CONTRATOS.CSV", "contratos",
        ["codigo_contrato", "id_processo", "id_licitacao", "contratacao",
         "status_contratacao", "dt_contratacao", "unidade", "processo", "processo_norm",
         "objeto", "tipo_aquisicao", "criterio_julgamento", "dt_inicio_vigencia",
         "dt_fim_vigencia", "fornecedor", "cpf_cnpj", "cnpj_norm", "id_forn",
         "valor_total_contrato", "valor_total_empenhado", "valor_total_liquidado",
         "valor_total_pago", "dt_public_deorj", "regime_juridico", "url_pncp",
         "data_extracao"],
        _contratos,
        {"codigo_contrato": "Código do Contrato", "id_processo": "ID Processo",
         "id_licitacao": "ID Licitação", "contratacao": "Contratação",
         "status_contratacao": "Status Contratação", "dt_contratacao": "Data Contratação",
         "unidade": "Unidade", "processo": "Processo", "objeto": "Objeto",
         "tipo_aquisicao": "Tipo de Aquisição",
         "criterio_julgamento": "Critério de Julgamento",
         "dt_inicio_vigencia": "Data Início Vigência",
         "dt_fim_vigencia": "Data Fim Vigência", "fornecedor": "Fornecedor",
         "cpf_cnpj": "CPF/CNPJ",
         "valor_total_contrato": "Valor Total Contrato/Valor Estimado para Contratação (R$)",
         "valor_total_empenhado": "Valor Total Empenhado (R$)",
         "valor_total_liquidado": "Valor Total Liquidado (R$)",
         "valor_total_pago": "Valor Total Pago (R$)",
         "dt_public_deorj": "Data Public DEORJ", "regime_juridico": "regimejuridico",
         "url_pncp": "URL PNCP", "data_extracao": "data_extracao"},
        _ID_FORN,
        ignoradas=("IDUG", "CodUG", "DATA_ASSINATURA"),
    ),
    Spec(
        "COMPRAS_DIRETAS.CSV", "compras_diretas",
        [*_COLUNAS_COMPRA, "ped", "temporalidade"],
        _compras_diretas,
        {**_CAMPOS_COMPRA, "ped": "PED", "temporalidade": "Temporalidade"},
        _ID_FORN,
    ),
    Spec(
        "OUTRAS_COMPRAS.CSV", "outras_compras",
        _COLUNAS_COMPRA, _outras_compras, _CAMPOS_COMPRA, _ID_FORN,
    ),
    Spec(
        "PROCESSOS_ELETRONICOS_DISPENSA.CSV", "ped",
        ["id_ped", "processo", "processo_norm", "ano_ped", "status_ped", "unidade",
         "nu_pesquisa", "objeto", "inicio_disputa", "fim_disputa", "id_item", "item",
         "qtd", "status_item", "justificativa", "fornecedor_vencedor", "id_forn",
         "cnpj_norm", "lances", "outras_propostas", "data_extracao"],
        _ped,
        {"id_ped": "ID PED", "processo": "Processo", "ano_ped": "Ano PED",
         "status_ped": "Status PED", "unidade": "Unidade",
         "nu_pesquisa": "N° da Pesquisa", "objeto": "Objeto",
         "inicio_disputa": "Início de Disputa", "fim_disputa": "Fim de Disputa",
         "id_item": "ID Item", "item": "Item", "qtd": "Qtd.",
         "status_item": "Status Item", "justificativa": "Justificativa",
         "fornecedor_vencedor": "Fornecedor Vencedor", "lances": "Lances",
         "outras_propostas": "Outras Propostas", "data_extracao": "data_extracao"},
        _ID_FORN,
    ),
    Spec(
        "ITENS_LICITACOES.CSV", "itens_licitacoes",
        ["id_licitacao", "licitacao", "unidade", "modalidade", "itens_lotes", "id_item",
         "familia", "classe", "artigo", "descricao", "quantidade",
         "valor_total_homologado", "taxa_homologada", "exclusivo_me_epp",
         "situacao_item", "dt_homologacao_licit", "data_extracao"],
        _itens_licitacoes,
        {"id_licitacao": "ID Licitação", "licitacao": "Licitação", "unidade": "Unidade",
         "modalidade": "Modalidade", "itens_lotes": "Itens/Lotes", "id_item": "ID Item",
         "familia": "Família", "classe": "Classe", "artigo": "Artigo",
         "descricao": "Descrição", "quantidade": "Quantidade",
         "valor_total_homologado": "Valor total Homologado (R$)",
         "taxa_homologada": "Taxa Homologada (%)", "exclusivo_me_epp": "Exclusivo ME/EPP",
         "situacao_item": "situacao_item", "dt_homologacao_licit": "data_homologacao_licit",
         "data_extracao": "data_extracao"},
    ),
    # A extração repete cada linha pelo nº de processos da ata: a carga divide a repetição.
    Spec(
        "ITENS_ATAS_REGISTRO_PRECO.CSV", "itens_atas_registro_preco",
        ["id_ata", "numero_ata", "criterio_julgamento", "id_item", "item", "fornecedor",
         "id_forn", "cnpj_norm", "qtd", "vl_unitario", "taxa_pct", "data_extracao"],
        _itens_atas,
        {"id_ata": "ID Ata", "numero_ata": "N° da Ata",
         "criterio_julgamento": "Critério de Julgamento", "id_item": "ID Item",
         "item": "Item", "fornecedor": "Fornecedor", "qtd": "Qtd",
         "vl_unitario": "Vl. Unitário", "taxa_pct": "Taxa %",
         "data_extracao": "data_extracao"},
        _ID_FORN,
        dedup=True,
    ),
    Spec(
        "PARTICIPANTES_ATAS_REGISTRO_PRECO.CSV", "participantes_atas_registro_preco",
        ["id_ata", "numero_ata", "unidade_participante", "criterio_julgamento", "item",
         "id_item", "qtd_demandada", "qtd_consumida", "valor_demandado",
         "valor_consumido", "data_extracao"],
        _part_atas,
        {"id_ata": "ID Ata", "numero_ata": "N° da Ata",
         "unidade_participante": "Unid. Participante",
         "criterio_julgamento": "Critério de Julgamento", "item": "Item",
         "id_item": "id item", "qtd_demandada": "Qtd Demandada",
         "qtd_consumida": "Qtd Consumida", "valor_demandado": "Valor Demandado",
         "valor_consumido": "Valor Consumido", "data_extracao": "data_extracao"},
        dedup=True,
    ),
    Spec(
        "ITENS_CONTRATOS.CSV", "itens_contratos",
        ["contratacao", "id_ata", "id_item", "item", "qtd_original", "vl_unit_original",
         "total_aditivada_suprimida", "vl_unit_aditivado_suprimido", "elemento",
         "subelemento", "data_extracao"],
        _itens_contratos,
        {"contratacao": "Contratação", "id_ata": "ID Ata", "id_item": "ID Item",
         "item": "Item", "qtd_original": "Qtde Original",
         "vl_unit_original": "VL. Unit.Original",
         "total_aditivada_suprimida": "Total Aditivada/Suprimida",
         "vl_unit_aditivado_suprimido": "VL. Unit.Aditivado/Suprimido",
         "elemento": "Elemento", "subelemento": "Subelemento",
         "data_extracao": "data_extracao"},
    ),
    Spec(
        "PARTICIPANTES.CSV", "participantes",
        ["id_lic", "nu_lic", "sigla", "unidade", "modalidade", "exclusivo_mpe",
         "id_familia", "familia", "id_classe", "classe", "id_artigo", "artigo", "id_item",
         "itens_lotes", "descricao", "quantidade", "situacao_item", "fornecedor",
         "data_cadastro", "mpe", "cpf_cnpj", "cnpj_norm", "id_forn",
         "fornecedor_vencedor", "valor_unit_ofertado", "taxa_ofertada", "data_extracao"],
        _participantes,
        {"id_lic": "ID_LIC", "nu_lic": "NU_LIC", "sigla": "SIGLA", "unidade": "UNIDADE",
         "modalidade": "MODALIDADE", "exclusivo_mpe": "EXCLUSIVO_MPE",
         "id_familia": "ID_FAMILIA", "familia": "FAMILIA", "id_classe": "ID_CLASSE",
         "classe": "CLASSE", "id_artigo": "ID_ARTIGO", "artigo": "ARTIGO",
         "id_item": "ID_ITEM", "itens_lotes": "ITENS_LOTES", "descricao": "DESCRICAO",
         "quantidade": "QUANTIDADE", "situacao_item": "SITUACAO_ITEM",
         "fornecedor": "FORNECEDOR_PARTICIPANTE", "data_cadastro": "data_cadastro",
         "mpe": "mpe", "cpf_cnpj": "CNPJ", "fornecedor_vencedor": "FORNECEDOR_VENCEDOR",
         "valor_unit_ofertado": "VALOR_UNIT_OFERTADO", "taxa_ofertada": "TAXA_OFERTADA",
         "data_extracao": "data_extracao"},
        {"id_forn": "ID FORN"},
    ),
    # O header tem 4 nomes; as linhas trazem um 5º valor (data de extração) sem nome.
    Spec(
        "FORNECEDOR_MAPEAMENTOS.CSV", "fornecedor_mapeamentos",
        ["cpf_cnpj", "cnpj_norm", "nome", "familia", "classe", "data_extracao"],
        _fmap,
        {"nome": "Nome/Razão Social", "cpf_cnpj": "CPF/CNPJ", "familia": "Família",
         "classe": "Classe"},
        {"data_extracao": "data_extracao"},
        sem_nome="data_extracao",
    ),
    Spec(
        "FORNECEDOR_HISTORICO_CONTRATACOES.CSV", "fornecedor_historico_contratacoes",
        ["nome", "cpf_cnpj", "cnpj_norm", "contratacao", "dt_contratacao", "processo",
         "processo_norm", "unidade", "valor_total_contratado", "valor_total_executado",
         "tipo_aquisicao", "data_extracao"],
        _fhc,
        {"nome": "Nome/Razão Social", "cpf_cnpj": "CPF/CNPJ", "contratacao": "Contratação",
         "dt_contratacao": "Data da Contratação", "processo": "Processo",
         "unidade": "Unidade", "valor_total_contratado": "Valor Total Contratado (R$)",
         "valor_total_executado": "Valor Total Executado (R$)",
         "tipo_aquisicao": "Tipo de Aquisição", "data_extracao": "data_extracao"},
    ),
    Spec(
        "HISTORICO_PRECOS_ATAS.CSV", "historico_precos_atas",
        ["tipo", "familia", "classe", "artigo", "id_item", "descricao", "ata_srp",
         "licitacao", "unidade_gestora", "fornecedor", "validade_ata", "qtd",
         "vl_unitario", "data_extracao"],
        _hp_atas,
        {**_CAMPOS_PRECO, "ata_srp": "Ata SRP", "licitacao": "Licitação",
         "unidade_gestora": "Unidade Gestora", "validade_ata": "Validade da Ata"},
    ),
    Spec(
        "HISTORICO_PRECOS_CD.CSV", "historico_precos_cd",
        ["tipo", "familia", "classe", "artigo", "id_item", "descricao", "id_processo",
         "processo", "processo_norm", "tipo_compra", "unidade_compradora", "fornecedor",
         "dt_aprovacao", "qtd", "vl_unitario", "contratacao", "data_extracao"],
        _hp_cd,
        {**_CAMPOS_PRECO, "id_processo": "ID Processo", "processo": "Processo",
         "tipo_compra": "Tipo de Compra", "unidade_compradora": "Unidade Compradora",
         "dt_aprovacao": "Data Aprovação", "contratacao": "Contratação"},
    ),
    Spec(
        "HISTORICO_PRECOS_LICIT.CSV", "historico_precos_licit",
        ["tipo", "familia", "classe", "artigo", "id_item", "descricao", "licitacao",
         "modalidade_compra", "unidade_compradora", "fornecedor", "dt_homologacao", "qtd",
         "vl_unitario", "contratacao", "data_extracao"],
        _hp_licit,
        {**_CAMPOS_PRECO, "licitacao": "Licitação",
         "modalidade_compra": "Modalidade de Compra",
         "unidade_compradora": "Unidade Compradora",
         "dt_homologacao": "Data Homologação", "contratacao": "Contratação"},
    ),
    Spec(
        "ACOMPANHAMENTO_ASSAPC.CSV", "acompanhamento_assapc",
        ["unidade", "processo", "processo_norm", "dt_criacao_processo", "status_processo",
         "valor_estimado", "contratacao", "dt_criacao_contratacao", "status_contrato",
         "modalidade", "vl_total_empenhado", "chave_siga", "dt_criacao_nadsiga",
         "dt_emissao_nadsiga", "ano", "fonte_recurso", "natureza",
         "valor_atual_contrato", "valor_original", "data_extracao"],
        _assapc,
        {"unidade": "UNIDADE", "processo": "PROCESSO",
         "dt_criacao_processo": "DATA_CRIACAO_PROCESSO",
         "status_processo": "STATUS_PROCESSO", "valor_estimado": "VALOR_ESTIMADO",
         "contratacao": "CONTRATACAO", "dt_criacao_contratacao": "DATA_CRIACAO_CONTRATACAO",
         "status_contrato": "STATUS_CONTRATO", "modalidade": "MODALIDADE",
         "vl_total_empenhado": "VL_TOTAL_EMPENHADO", "chave_siga": "CHAVE_SIGA",
         "dt_criacao_nadsiga": "DATA_CRIACAO_NADSIGA",
         "dt_emissao_nadsiga": "DATA_EMISSAO_NADSIGA", "ano": "ANO",
         "fonte_recurso": "FONTE_RECURSO", "natureza": "NATUREZA",
         "valor_atual_contrato": "VALOR_ATUAL_CONTRATO", "valor_original": "VALOR_ORIGINAL",
         "data_extracao": "data_extracao"},
    ),
    Spec(
        "SANCOES.CSV", "sancoes",
        ["nome", "cpf_cnpj", "cnpj_norm", "id_forn", "enquadramento_legal",
         "numero_processo", "processo_norm", "dt_efetivacao", "prazo", "dt_inicio",
         "dt_final", "justificativa", "motivo", "orgao_apenador", "status",
         "data_extracao"],
        _sancoes,
        {"nome": "Nome/Razão Social", "cpf_cnpj": "CPF/CNPJ",
         "enquadramento_legal": "Enquadramento Legal",
         "numero_processo": "Número do processo", "dt_efetivacao": "Data de Efetivação",
         "prazo": "Prazo", "dt_inicio": "Data Início", "dt_final": "Data Final",
         "justificativa": "Justificativa", "motivo": "Motivo",
         "orgao_apenador": "Órgão/Entidade Apenadora", "status": "Status",
         "data_extracao": "data_extracao"},
        _ID_FORN,
    ),
    Spec(
        "FORNECEDOR_SANCOES.CSV", "fornecedor_sancoes",
        ["nome", "cpf_cnpj", "cnpj_norm", "id_forn", "orgao_apenador",
         "enquadramento_legal", "motivo", "contrato", "dt_efetivacao",
         "status_penalidade", "data_extracao"],
        _fornecedor_sancoes,
        {"nome": "Nome/Razão Social", "cpf_cnpj": "CPF/CNPJ",
         "orgao_apenador": "Órgão/Entidade Apenadora",
         "enquadramento_legal": "Enquadramento Legal", "motivo": "Motivo",
         "contrato": "Contrato", "dt_efetivacao": "Data de Efetivação",
         "status_penalidade": "Status da Penalidade", "data_extracao": "data_extracao"},
        _ID_FORN,
    ),
]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _validar(specs: list[Spec], csv_dir: Path) -> bool:
    """Confere arquivos e headers antes de carregar qualquer coisa."""
    ok = True
    for spec in specs:
        path = csv_dir / spec.csv
        if not path.exists():
            print(f"  ✗ {spec.csv} não encontrado em {csv_dir}", file=sys.stderr)
            ok = False
            continue
        _, faltando, desconhecidas = _cabecalho(_ler_header(path), spec)
        if faltando:
            print(f"  ✗ {spec.csv}: colunas obrigatórias ausentes: {', '.join(faltando)}",
                  file=sys.stderr)
            ok = False
        if desconhecidas:
            print(f"  ! {spec.csv}: colunas desconhecidas (não carregadas): "
                  f"{', '.join(desconhecidas)}", file=sys.stderr)
    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/siga.db"))
    parser.add_argument("--csv-dir", type=Path, default=Path("data/csv"))
    parser.add_argument("--only", default=None,
                        help="Carrega só uma tabela (nome SQL)")
    parser.add_argument("--skip-indexes", action="store_true")
    args = parser.parse_args(argv)

    if not args.db.exists():
        print(f"DB não existe: {args.db}", file=sys.stderr)
        return 1

    specs = [sp for sp in SPECS if not args.only or sp.tabela == args.only]
    if not specs:
        print(f"Tabela desconhecida: {args.only}", file=sys.stderr)
        return 1
    # FORNECEDORES.CSV e ATA_REGISTRO_PRECO.CSV são sempre lidos: dão as chaves para ID Forn
    # e documentos mascarados e o nº de processos de cada ata.
    validar = [sp for sp in (_FORNECEDORES, _ATAS) if sp not in specs] + specs
    if not _validar(validar, args.csv_dir):
        print("Abortado: corrija os CSVs acima.", file=sys.stderr)
        return 1
    _ler_fornecedores(args.csv_dir / _FORNECEDORES.csv)
    _ler_atas(args.csv_dir / _ATAS.csv)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -200000;")  # ~200MB
    conn.execute("PRAGMA mmap_size = 268435456;")

    total_t0 = time.time()
    for spec in specs:
        print(f"→ {spec.tabela}  ({spec.csv})", flush=True)
        _load(conn, spec, args.csv_dir / spec.csv)

    if not args.skip_indexes and not args.only:
        print("→ Criando índices…", flush=True)
        idx_path = Path(__file__).parent / "indexes.sql"
        conn.executescript(idx_path.read_text())
        conn.commit()
        print("  ✓ Índices criados.")

    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute("ANALYZE;")
    conn.close()
    print(f"\nConcluído em {time.time() - total_t0:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
