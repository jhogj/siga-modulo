"""Detalhe: ata de registro de preços.

Contexto entregue ao template `pages/ata.html`:
- `ata`: linha de atas_registro_preco;
- `licitacao`: licitação de origem (ou None quando o id_licitacao é órfão);
- `fornecedores`: [{fornecedor, cnpj_norm, cpf_cnpj, itens, valor}] por valor registrado;
- `processos`: todos os processos da ata (ata_processos), o da própria ata primeiro (só na página);
- `numeros`: {itens, fornecedores, valor, contratos, orgaos};
- página: `itens`, `contratos`, `orgaos` (prévias de `corte(total)` linhas);
- seção: `linhas` e `pag` (paginação de 25).
"""
from __future__ import annotations

from . import _comum

SECOES = ("itens", "contratos", "orgaos")

# cnpj_norm vem do ID Forn na carga; sem ele (layout antigo), a chave é resolvida pelo nome.
_SQL_FORNECEDORES = (
    "SELECT fornecedor, cnpj_norm, count(*) itens, sum(qtd * vl_unitario) valor, "
    "sum(qtd IS NULL OR vl_unitario IS NULL OR vl_unitario <= 0) sem_valor "
    "FROM itens_atas_registro_preco WHERE id_ata = ? GROUP BY fornecedor, cnpj_norm ORDER BY valor DESC")

_SQL_ITENS = (
    "SELECT id_item, item, fornecedor, cnpj_norm, qtd, vl_unitario FROM itens_atas_registro_preco "
    "WHERE id_ata = ? ORDER BY item LIMIT ? OFFSET ?")

_SQL_PROCESSOS = (
    "SELECT processo FROM ata_processos WHERE id_ata = ? AND processo IS NOT NULL "
    "ORDER BY processo_norm IS NOT ?, id_processo, processo_norm")

_SUB_CONTRATOS = "SELECT DISTINCT contratacao FROM itens_contratos WHERE id_ata = ?"
_SQL_CONTRATOS = (
    "SELECT c.contratacao, c.dt_contratacao, c.unidade, c.fornecedor, c.cnpj_norm, "
    "c.valor_total_contrato, c.status_contratacao, c.dt_fim_vigencia FROM contratos c "
    f"WHERE c.contratacao IN ({_SUB_CONTRATOS}) ORDER BY c.dt_contratacao DESC LIMIT ? OFFSET ?")
_SQL_N_CONTRATOS = f"SELECT count(*) FROM contratos WHERE contratacao IN ({_SUB_CONTRATOS})"

_SQL_ORGAOS = (
    "SELECT unidade_participante, count(DISTINCT id_item) itens, "
    "count(DISTINCT CASE WHEN qtd_consumida > 0 THEN id_item END) consumidos "
    "FROM participantes_atas_registro_preco WHERE id_ata = ? GROUP BY unidade_participante "
    "ORDER BY itens DESC, unidade_participante LIMIT ? OFFSET ?")
_SQL_N_ORGAOS = ("SELECT count(DISTINCT coalesce(unidade_participante, '')) "
                 "FROM participantes_atas_registro_preco WHERE id_ata = ?")


def _base(conn, id_ata) -> dict | None:
    r = conn.execute("SELECT * FROM atas_registro_preco WHERE id_ata = ?", (id_ata,)).fetchone()
    if not r:
        return None
    ata = dict(r)
    lic = None
    if ata.get("id_licitacao") is not None:
        lr = conn.execute("SELECT id_licitacao, licitacao, modalidade, unidade FROM licitacoes "
                          "WHERE id_licitacao = ?", (ata["id_licitacao"],)).fetchone()
        lic = dict(lr) if lr else None

    fornecedores = []
    for f in conn.execute(_SQL_FORNECEDORES, (id_ata,)).fetchall():
        if not f["fornecedor"]:
            continue
        # Soma parcial não é valor registrado: item sem quantidade ou preço deixa o total em branco.
        valor = f["valor"] if not f["sem_valor"] and f["valor"] and f["valor"] > 0 else None
        fornecedores.append({
            "fornecedor": f["fornecedor"], "itens": f["itens"], "valor": valor,
            "completo": not f["sem_valor"],
            "cnpj_norm": f["cnpj_norm"] or _comum.cnpj_por_nome(conn, f["fornecedor"], ata.get("id_licitacao")),
        })
    # Documento para exibição: sempre o cpf_cnpj do cadastro, nunca a chave.
    chaves = [f["cnpj_norm"] for f in fornecedores if f["cnpj_norm"]]
    docs = {r[0]: r[1] for r in conn.execute(
        f"SELECT cnpj_norm, cpf_cnpj FROM fornecedores WHERE cnpj_norm IN ({', '.join('?' * len(chaves))})",
        chaves)} if chaves else {}
    for f in fornecedores:
        f["cpf_cnpj"] = docs.get(f["cnpj_norm"])

    n_itens = sum(f["itens"] for f in fornecedores)
    total = None
    if fornecedores and all(f["completo"] for f in fornecedores):
        total = sum(f["valor"] or 0 for f in fornecedores) or None

    numeros = {
        "itens": n_itens,
        "fornecedores": len(fornecedores),
        "valor": total,
        "contratos": conn.execute(_SQL_N_CONTRATOS, (id_ata,)).fetchone()[0],
        "orgaos": conn.execute(_SQL_N_ORGAOS, (id_ata,)).fetchone()[0],
    }
    return {"ata": ata, "licitacao": lic, "fornecedores": fornecedores, "numeros": numeros,
            "cnpjs": {f["fornecedor"]: f["cnpj_norm"] for f in fornecedores if f["cnpj_norm"]}}


def _itens(conn, id_ata, limite, offset, cnpjs):
    linhas = [dict(r) for r in conn.execute(_SQL_ITENS, (id_ata, limite, offset)).fetchall()]
    for r in linhas:
        r["cnpj_norm"] = r["cnpj_norm"] or cnpjs.get(r["fornecedor"])
        if r["vl_unitario"] is not None and r["vl_unitario"] <= 0:
            r["vl_unitario"] = None  # preço zerado não é preço (itens por taxa)
    return linhas


def _contratos(conn, id_ata, limite, offset):
    linhas = [dict(r) for r in conn.execute(_SQL_CONTRATOS, (id_ata, limite, offset)).fetchall()]
    for r in linhas:
        if r["valor_total_contrato"] is not None and r["valor_total_contrato"] <= 0:
            r["valor_total_contrato"] = None
    return linhas


def _orgaos(conn, id_ata, limite, offset):
    return [dict(r) for r in conn.execute(_SQL_ORGAOS, (id_ata, limite, offset)).fetchall()]


def _consulta(conn, id_ata, nome, limite, offset, cnpjs):
    if nome == "itens":
        return _itens(conn, id_ata, limite, offset, cnpjs)
    if nome == "contratos":
        return _contratos(conn, id_ata, limite, offset)
    return _orgaos(conn, id_ata, limite, offset)


def _processos(conn, ata) -> list[str]:
    rows = conn.execute(_SQL_PROCESSOS, (ata["id_ata"], ata.get("processo_norm"))).fetchall()
    return [r[0] for r in rows] or ([ata["processo"]] if ata.get("processo") else [])


def get(conn, id_ata):
    dados = _base(conn, id_ata)
    if dados is None:
        return None
    dados["processos"] = _processos(conn, dados["ata"])
    n, cnpjs = dados["numeros"], dados["cnpjs"]
    for nome in SECOES:
        total = n[nome]
        dados[nome] = _consulta(conn, id_ata, nome, _comum.corte(total), 0, cnpjs) if total else []
    return dados


def secao(conn, id_ata, nome, pagina):
    if nome not in SECOES:
        return None
    dados = _base(conn, id_ata)
    if dados is None:
        return None
    if not dados["numeros"][nome]:  # seção sem linhas não existe
        return None
    pag = _comum.paginar(dados["numeros"][nome], pagina)
    dados["pag"] = pag
    dados["linhas"] = _consulta(conn, id_ata, nome, pag["por_pagina"], pag["offset"], dados["cnpjs"])
    return dados
