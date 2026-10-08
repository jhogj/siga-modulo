"""Detalhe: licitação — /siga/licitacoes/{id_licitacao} e /{secao}."""
from __future__ import annotations

import re

from .. import fmt, regras
from . import _comum

SECOES = ("participantes", "itens", "atas", "contratos")

TITULOS = {
    "participantes": "Fornecedores participantes",
    "atas": "Atas de registro de preços geradas",
    "contratos": "Contratos gerados",
    "itens": "Itens",
}

# A descrição do item traz o ID interno e o código no fim ("… - ID:3400 - Código do Item:8905.001.0002").
_SUFIXO_ID = re.compile(r"\s*-\s*ID:\s*\d+(\s*-\s*Código do Item:\s*[\w.]*)?\s*$")

_SQL_PARTICIPANTES = """
SELECT cnpj_norm, max(fornecedor) fornecedor, count(DISTINCT id_item) disputados,
       count(DISTINCT CASE WHEN fornecedor_vencedor='Sim' THEN id_item END) vencidos,
       sum(CASE WHEN fornecedor_vencedor='Sim' THEN valor_unit_ofertado*quantidade END) valor_vencido
FROM participantes WHERE id_lic = ? AND cnpj_norm IS NOT NULL
GROUP BY cnpj_norm ORDER BY vencidos DESC, disputados DESC LIMIT ? OFFSET ?"""

# O vencedor de cada item sai de _comum.vencedor (por lote, ordem determinística).
_SQL_ITENS = """
SELECT i.id_item, i.itens_lotes, i.descricao, i.quantidade, i.valor_total_homologado, i.situacao_item
FROM itens_licitacoes i WHERE i.id_licitacao = ?
ORDER BY CAST(substr(i.itens_lotes, 7) AS INTEGER) LIMIT ? OFFSET ?"""

_SQL_ATAS = """
SELECT id_ata, numero_ata, unidade_gerenciadora, inicio_validade, fim_validade, status_ata
FROM atas_registro_preco WHERE id_licitacao = ? ORDER BY inicio_validade DESC LIMIT ? OFFSET ?"""

_SQL_CONTRATOS = """
SELECT contratacao, dt_contratacao, fornecedor, cnpj_norm, valor_total_contrato, status_contratacao, dt_fim_vigencia
FROM contratos WHERE id_licitacao = ? ORDER BY dt_contratacao DESC LIMIT ? OFFSET ?"""

_SQL_TOTAIS = """
SELECT (SELECT count(DISTINCT cnpj_norm) FROM participantes WHERE id_lic = :id AND cnpj_norm IS NOT NULL) participantes,
       (SELECT count(*) FROM itens_licitacoes WHERE id_licitacao = :id) itens,
       (SELECT count(*) FROM atas_registro_preco WHERE id_licitacao = :id) atas,
       (SELECT count(*) FROM contratos WHERE id_licitacao = :id) contratos"""


def _positivo(v) -> float | None:
    """Valor monetário > 0; zero e nulo são ausência de dado (o SIGA grava 0 em item sem resultado)."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _participante(r) -> dict:
    d = dict(r)
    d["valor_vencido"] = _positivo(d["valor_vencido"])
    return d


def _item(r) -> dict:
    d = dict(r)
    d["descricao"] = _SUFIXO_ID.sub("", d["descricao"] or "").strip()
    total = _positivo(d["valor_total_homologado"])
    qtd = d["quantidade"] or 0
    d["valor_total"] = total
    d["valor_unitario"] = total / qtd if (total is not None and qtd > 0) else None
    return d


def _contrato(r) -> dict:
    d = dict(r)
    d["valor"] = _positivo(d["valor_total_contrato"])
    return d


_CONSULTAS = {
    "participantes": (_SQL_PARTICIPANTES, _participante),
    "itens": (_SQL_ITENS, _item),
    "atas": (_SQL_ATAS, dict),
    "contratos": (_SQL_CONTRATOS, _contrato),
}

# Colunas opcionais por seção: só aparecem se alguma linha visível tiver o dado.
_COLUNAS = {
    "participantes": ("valor_vencido",),
    "itens": ("quantidade", "valor_unitario", "valor_total", "vencedor", "situacao_item"),
    "contratos": ("dt_contratacao", "fornecedor", "valor"),
    "atas": (),
}


def _presente(v) -> bool:
    return v is not None and str(v).strip().lower() not in ("", "none", "null", "nan")


def _linhas(conn, id_licitacao: int, nome: str, limite: int, offset: int = 0) -> list[dict]:
    sql, conv = _CONSULTAS[nome]
    linhas = [conv(r) for r in conn.execute(sql, (id_licitacao, limite, offset)).fetchall()]
    if nome == "itens":
        for d in linhas:
            d["vencedor"], d["vencedor_cnpj"], d["vencedor_mais"] = _comum.vencedor(
                conn, id_licitacao, d["id_item"], d["itens_lotes"])
    return linhas


def _colunas(nome: str, linhas: list[dict]) -> dict:
    return {c: any(_presente(l.get(c)) for l in linhas) for c in _COLUNAS[nome]}


def _base(conn, id_licitacao):
    r = conn.execute("SELECT * FROM licitacoes WHERE id_licitacao = ?", (id_licitacao,)).fetchone()
    if not r:
        return None, None
    totais = dict(conn.execute(_SQL_TOTAIS, {"id": id_licitacao}).fetchone())
    return dict(r), totais


def _variacao(estimado, homologado) -> str | None:
    """Nota "X% abaixo/acima do estimado", só quando os dois valores são > 0 e a diferença aparece em 0,1%."""
    e, h = _positivo(estimado), _positivo(homologado)
    if e is None or h is None:
        return None
    p = round((h - e) / e * 100, 1)
    if p == 0:
        return None
    texto = f"{abs(p):.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{texto}% {'abaixo' if p < 0 else 'acima'} do estimado"


def _status(lic) -> dict:
    """Meta do cabeçalho: "Homologado em dd/mm/aaaa" quando há data de homologação; alerta nos negativos."""
    st = (lic["status"] or "").strip()
    quando = fmt.data(lic["dt_homologacao"])
    texto = f"{st} em {quando}" if (st in regras.LIC_HOMOLOGADAS and quando) else st
    return {"texto": texto, "alerta": regras.alerta_licitacao(st)}


def get(conn, id_licitacao):
    lic, totais = _base(conn, id_licitacao)
    if lic is None:
        return None
    secoes = {}
    for nome in SECOES:
        total = totais[nome]
        if not total:
            continue  # seção sem linhas não existe
        linhas = _linhas(conn, id_licitacao, nome, _comum.corte(total))
        secoes[nome] = {"titulo": TITULOS[nome], "total": total, "linhas": linhas,
                        "colunas": _colunas(nome, linhas)}
    return {
        "licitacao": lic,
        "totais": totais,
        "status": _status(lic),
        "estimado": _positivo(lic["valor_total_estimado"]),
        "homologado": _positivo(lic["valor_total_homologado"]),
        "variacao": _variacao(lic["valor_total_estimado"], lic["valor_total_homologado"]),
        "secoes": secoes,
    }


def secao(conn, id_licitacao, nome, pagina):
    if nome not in SECOES:
        return None
    lic, totais = _base(conn, id_licitacao)
    if lic is None:
        return None
    total = totais[nome]
    if not total:
        return None  # seção sem linhas não existe (404), como na página
    pag = _comum.paginar(total, pagina)
    linhas = _linhas(conn, id_licitacao, nome, pag["por_pagina"], pag["offset"])
    return {
        "licitacao": lic,
        "totais": totais,
        "nome_secao": nome,
        "titulo_secao": TITULOS[nome],
        "linhas": linhas,
        "colunas": _colunas(nome, linhas),
        "pag": pag,
    }
