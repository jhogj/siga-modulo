"""Detalhe: fornecedor — página e listas completas de contratos, compras e licitações."""
from __future__ import annotations

import re

from ..regras import CANCELADOS, situacao_sancao
from . import _comum

SECOES = ("contratos", "compras", "licitacoes")

_CANC = "(" + ", ".join("?" * len(CANCELADOS)) + ")"
MAX_AREAS = 12  # acima disso, "e mais N"


def chave_antiga(conn, digitos: str) -> str | None:
    """Chave atual de quem tinha só os dígitos do documento como chave (CPF mascarado,
    documento zerado): a chave 'F…' com esses dígitos, se for exatamente uma."""
    chaves = [c for c, doc in conn.execute(
        "SELECT cnpj_norm, cpf_cnpj FROM fornecedores WHERE cnpj_norm >= 'F' AND cnpj_norm < 'G'")
        if re.sub(r"\D", "", doc or "") == digitos]
    return chaves[0] if len(chaves) == 1 else None


def _base(conn, cnpj_norm):
    r = conn.execute("SELECT * FROM fornecedores WHERE cnpj_norm = ?", (cnpj_norm,)).fetchone()
    return dict(r) if r else None


def _agregado_contratos(conn, cnpj_norm) -> dict:
    r = conn.execute(
        f"SELECT coalesce(sum(status_contratacao NOT IN {_CANC}), 0) n_validos, "
        f"coalesce(sum(status_contratacao IN {_CANC}), 0) n_cancelados, count(*) n_total, "
        f"sum(CASE WHEN status_contratacao NOT IN {_CANC} THEN valor_total_contrato END) valor "
        "FROM contratos WHERE cnpj_norm = ?",
        (*CANCELADOS, *CANCELADOS, *CANCELADOS, cnpj_norm)).fetchone()
    return dict(r)


def _n_compras(conn, cnpj_norm) -> int:
    return conn.execute(
        "SELECT (SELECT count(DISTINCT id_processo) FROM compras_diretas WHERE cnpj_norm = ?)"
        " + (SELECT count(DISTINCT id_processo) FROM outras_compras WHERE cnpj_norm = ?)",
        (cnpj_norm, cnpj_norm)).fetchone()[0] or 0


def _agregado_licitacoes(conn, cnpj_norm) -> dict:
    r = conn.execute(
        "SELECT count(DISTINCT id_lic) n, "
        "count(DISTINCT CASE WHEN fornecedor_vencedor = 'Sim' THEN id_lic END) vencidas "
        "FROM participantes WHERE cnpj_norm = ?", (cnpj_norm,)).fetchone()
    return {"n": r["n"] or 0, "vencidas": r["vencidas"] or 0}


def _sancoes(conn, cnpj_norm) -> list[dict]:
    """Só a tabela `sancoes` (fornecedor_sancoes é a mesma base duplicada). Vigentes no topo."""
    linhas = []
    for r in conn.execute("SELECT * FROM sancoes WHERE cnpj_norm = ? ORDER BY dt_efetivacao DESC", (cnpj_norm,)):
        s = dict(r)
        s["situacao"] = situacao_sancao(s["status"], s["dt_final"])
        linhas.append(s)
    linhas.sort(key=lambda s: not s["situacao"]["vigente"])  # estável: mantém a data decrescente
    return linhas


def _orgaos(conn, cnpj_norm) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT unidade, count(*) n, sum(valor_total_contrato) v FROM contratos "
        f"WHERE cnpj_norm = ? AND status_contratacao NOT IN {_CANC} "
        "GROUP BY unidade ORDER BY v DESC LIMIT 5", (cnpj_norm, *CANCELADOS))]


def _contratos(conn, cnpj_norm, limite, offset=0) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT contratacao, dt_contratacao, unidade, objeto, valor_total_contrato, status_contratacao, "
        "dt_fim_vigencia FROM contratos WHERE cnpj_norm = ? "
        "ORDER BY dt_contratacao DESC NULLS LAST, contratacao DESC LIMIT ? OFFSET ?",
        (cnpj_norm, limite, offset))]


def _compras(conn, cnpj_norm, limite, offset=0) -> list[dict]:
    """Agrupadas por processo; o valor é a soma dos itens deste fornecedor."""
    return [dict(r) for r in conn.execute(
        """SELECT id_processo, max(processo) processo, max(unidade) unidade, max(afastamento) afastamento,
                  max(dt_aprovacao) dt, count(*) n_itens, sum(qtd * vl_unitario) valor
           FROM (SELECT id_processo, processo, unidade, afastamento, dt_aprovacao, qtd, vl_unitario
                   FROM compras_diretas WHERE cnpj_norm = :c
                 UNION ALL
                 SELECT id_processo, processo, unidade, afastamento, dt_aprovacao, qtd, vl_unitario
                   FROM outras_compras WHERE cnpj_norm = :c)
           GROUP BY id_processo ORDER BY dt DESC, id_processo DESC LIMIT :lim OFFSET :off""",
        {"c": cnpj_norm, "lim": limite, "off": offset})]


def _licitacoes(conn, cnpj_norm, limite, offset=0) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT p.id_lic, l.licitacao, l.modalidade, l.unidade,
                  coalesce(l.dt_homologacao, l.dt_abertura) dt,
                  count(DISTINCT p.id_item) disputados,
                  count(DISTINCT CASE WHEN p.fornecedor_vencedor = 'Sim' THEN p.id_item END) vencidos
           FROM participantes p JOIN licitacoes l ON l.id_licitacao = p.id_lic
           WHERE p.cnpj_norm = ? GROUP BY p.id_lic ORDER BY dt DESC, p.id_lic DESC LIMIT ? OFFSET ?""",
        (cnpj_norm, limite, offset))]


def _areas(conn, cnpj_norm) -> list[str]:
    """Famílias com espaços colapsados e sem ponto final (o parágrafo ganha um só ponto no fim)."""
    areas = []
    for (familia,) in conn.execute(
            "SELECT DISTINCT familia FROM fornecedor_mapeamentos WHERE cnpj_norm = ? AND familia IS NOT NULL "
            "ORDER BY familia", (cnpj_norm,)):
        a = " ".join((familia or "").split()).rstrip(" .;,")
        if a and a not in areas:
            areas.append(a)
    return areas


def get(conn, cnpj_norm):
    f = _base(conn, cnpj_norm)
    if not f:
        return None
    ag = _agregado_contratos(conn, cnpj_norm)
    n_compras = _n_compras(conn, cnpj_norm)
    lic = _agregado_licitacoes(conn, cnpj_norm)
    sancoes = _sancoes(conn, cnpj_norm)
    vigentes = [s for s in sancoes if s["situacao"]["vigente"]]
    areas = _areas(conn, cnpj_norm)
    return {
        "fornecedor": f,
        "contratos_ag": ag,
        "n_compras": n_compras,
        "lic": lic,
        "sancoes": sancoes,
        "n_vigentes": len(vigentes),
        "sancao_aviso": max(vigentes, key=lambda s: s["dt_efetivacao"] or "") if vigentes else None,
        "orgaos": _orgaos(conn, cnpj_norm) if ag["n_validos"] else [],
        "contratos": _contratos(conn, cnpj_norm, _comum.corte(ag["n_total"])) if ag["n_total"] else [],
        "compras": _compras(conn, cnpj_norm, _comum.corte(n_compras)) if n_compras else [],
        "licitacoes": _licitacoes(conn, cnpj_norm, _comum.corte(lic["n"])) if lic["n"] else [],
        "areas": areas[:MAX_AREAS],
        "areas_mais": max(0, len(areas) - MAX_AREAS),
    }


def secao(conn, cnpj_norm, nome, pagina):
    if nome not in SECOES:
        return None
    f = _base(conn, cnpj_norm)
    if not f:
        return None
    n_cancelados = 0  # a lista de contratos inclui os cancelados; o cabeçalho diz quantos
    if nome == "contratos":
        ag = _agregado_contratos(conn, cnpj_norm)
        total, consulta, n_cancelados = ag["n_total"], _contratos, ag["n_cancelados"]
    elif nome == "compras":
        total, consulta = _n_compras(conn, cnpj_norm), _compras
    else:
        total, consulta = _agregado_licitacoes(conn, cnpj_norm)["n"], _licitacoes
    if not total:  # seção sem linhas não existe
        return None
    pag = _comum.paginar(total, pagina)
    return {"fornecedor": f, "linhas": consulta(conn, cnpj_norm, pag["por_pagina"], pag["offset"]), "pag": pag,
            "n_cancelados": n_cancelados}
