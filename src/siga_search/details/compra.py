"""Detalhe: compra. Um registro por processo (`id_processo`).

As linhas do processo vêm de `compras_diretas` ou, se não houver, de `outras_compras`.
Cabeçalho, números e ficha usam a primeira linha (os campos do processo são constantes nele);
itens e fornecedores saem das próprias linhas, já em memória.
"""
from __future__ import annotations

from . import _comum

SECOES = ("itens", "contratos")
TITULOS = {"itens": "Itens comprados", "contratos": "Contratos gerados"}

_TABELAS = ("compras_diretas", "outras_compras")


def _positivo(v):
    """Valor monetário só existe se o banco o sustenta: nulo e zero viram None (nunca "R$ 0,00").

    Os zeros de `vl_unitario` são preços abaixo de um centavo arredondados (ex.: 612.000 un. num
    processo de R$ 7.294,00); o único `valor_processo` zero está num processo sem preço algum.
    """
    return v if isinstance(v, (int, float)) and v > 0 else None


def _linhas(conn, id_processo):
    for tabela in _TABELAS:
        rows = conn.execute(f"SELECT rowid, * FROM {tabela} WHERE id_processo = ?", (id_processo,)).fetchall()
        if rows:
            return [dict(r) for r in rows]
    return None


def _itens(linhas):
    """Linhas que são de fato itens (há processos com uma única linha sem item), ordenadas por item."""
    itens = []
    for r in linhas:
        if not (r.get("item") or r.get("id_item")):
            continue
        qtd = r.get("qtd")
        unit = _positivo(r.get("vl_unitario"))
        r["vl_unitario"] = unit
        r["total"] = _positivo(qtd * unit) if (unit is not None and isinstance(qtd, (int, float))) else None
        r["fornecedor_chave"] = r.get("cnpj_norm") or r.get("fornecedor_vencedor") or None
        itens.append(r)
    itens.sort(key=lambda r: ((r.get("item") or "").strip(), r["rowid"]))
    return itens


def _fornecedores(itens):
    """Agregação por coalesce(cnpj_norm, fornecedor_vencedor): itens = count, valor = sum(qtd*vl_unitario)."""
    grupos: dict[str, dict] = {}
    for r in itens:
        chave = r["fornecedor_chave"]
        if not chave:
            continue
        g = grupos.get(chave)
        if g is None:
            g = grupos[chave] = {"nome": r.get("fornecedor_vencedor") or r.get("cpf_cnpj") or "",
                                 "cnpj_norm": r.get("cnpj_norm"), "cpf_cnpj": r.get("cpf_cnpj"),
                                 "itens": 0, "valor": None}
        g["itens"] += 1
        if r["total"] is not None:
            g["valor"] = (g["valor"] or 0) + r["total"]
    return sorted(grupos.values(), key=lambda g: (-(g["valor"] or 0), -g["itens"], g["nome"]))


def _contratos(conn, id_processo):
    linhas = [dict(r) for r in conn.execute(
        "SELECT contratacao, dt_contratacao, fornecedor, cnpj_norm, valor_total_contrato, "
        "status_contratacao, dt_fim_vigencia FROM contratos WHERE id_processo = ? "
        "ORDER BY dt_contratacao DESC", (id_processo,)).fetchall()]
    for r in linhas:
        r["valor_total_contrato"] = _positivo(r["valor_total_contrato"])  # como em ata e licitação
    return linhas


def _disputa(conn, id_processo):
    """Disputa eletrônica (PED): o ID PED é o próprio ID Processo da compra."""
    r = conn.execute("SELECT min(inicio_disputa) ini, max(fim_disputa) fim FROM ped WHERE id_ped = ?",
                     (id_processo,)).fetchone()
    if not r or not (r["ini"] or r["fim"]):
        return None
    return {"ini": r["ini"], "fim": r["fim"]}


def _base(linhas, id_processo):
    compra = dict(linhas[0])
    compra["id_processo"] = id_processo
    compra["valor_processo"] = _positivo(compra.get("valor_processo"))
    return compra


def get(conn, id_processo):
    linhas = _linhas(conn, id_processo)
    if not linhas:
        return None
    compra = _base(linhas, id_processo)
    itens = _itens(linhas)
    fornecedores = _fornecedores(itens)
    contratos = _contratos(conn, id_processo)
    return {
        "compra": compra,
        "itens": itens[:_comum.corte(len(itens))],
        "n_itens": len(itens),
        "fornecedores": fornecedores,
        "contratos": contratos[:_comum.corte(len(contratos))],
        "n_contratos": len(contratos),
        "disputa": _disputa(conn, id_processo),
        "titulos": TITULOS,
    }


def secao(conn, id_processo, nome, pagina):
    if nome not in SECOES:
        return None
    linhas = _linhas(conn, id_processo)
    if not linhas:
        return None
    compra = _base(linhas, id_processo)
    itens = _itens(linhas)
    todas = itens if nome == "itens" else _contratos(conn, id_processo)
    if not todas:  # seção sem linhas não existe
        return None
    pag = _comum.paginar(len(todas), pagina)
    return {
        "compra": compra,
        "fornecedores": _fornecedores(itens) if nome == "itens" else [],
        "linhas": todas[pag["offset"]:pag["offset"] + pag["por_pagina"]],
        "pag": pag,
        "titulos": TITULOS,
    }
