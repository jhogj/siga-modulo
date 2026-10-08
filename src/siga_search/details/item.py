"""Detalhe: item do catálogo.

Uma página só, sem seções: os preços registrados de todas as origens numa tabela
paginada, com filtro de origem (?origem=) e página (?pagina=).
"""
from __future__ import annotations

from datetime import date

from . import _comum

ORIGENS = ("contratos", "compras", "licitacoes", "atas")

ROTULO_ORIGEM = {"contratos": "Contratos", "compras": "Compras", "licitacoes": "Licitações", "atas": "Atas"}

_CONTAGEM = """
SELECT 'contratos', count(*) FROM itens_contratos WHERE id_item = :i
UNION ALL SELECT 'compras', (SELECT count(*) FROM compras_diretas WHERE id_item = :i)
                          + (SELECT count(*) FROM outras_compras WHERE id_item = :i)
UNION ALL SELECT 'licitacoes', count(*) FROM itens_licitacoes WHERE id_item = :i
UNION ALL SELECT 'atas', count(*) FROM itens_atas_registro_preco WHERE id_item = :i
"""

# Um ramo da união por origem; todo ramo nomeia as colunas, porque pode ser o único. Colunas: origem, dt, ref, chave, unidade, fornecedor, cnpj_norm, qtd, un, vu, lote.
# Em licitações, o vencedor é preenchido depois, por _comum.vencedor (precisa do lote).
_RAMOS = {
    "contratos": """
SELECT 'contratos' origem, c.dt_contratacao dt, c.contratacao ref, c.contratacao chave, c.unidade,
       c.fornecedor, c.cnpj_norm, i.qtd_original qtd, NULL un, i.vl_unit_original vu, NULL lote
  FROM itens_contratos i JOIN contratos c ON c.contratacao = i.contratacao WHERE i.id_item = :i""",
    "compras": """
SELECT 'compras' origem, dt_aprovacao dt, processo ref, id_processo chave, unidade,
       fornecedor_vencedor fornecedor, cnpj_norm, qtd, unidade_medida un, vl_unitario vu, NULL lote
  FROM compras_diretas WHERE id_item = :i
UNION ALL
SELECT 'compras', dt_aprovacao, processo, id_processo, unidade, fornecedor_vencedor, cnpj_norm, qtd, unidade_medida, vl_unitario, NULL
  FROM outras_compras WHERE id_item = :i""",
    "licitacoes": """
SELECT 'licitacoes' origem, coalesce(l.dt_homologacao, l.dt_abertura) dt, l.licitacao ref, l.id_licitacao chave, l.unidade,
       NULL fornecedor, NULL cnpj_norm,
       i.quantidade qtd, NULL un, CASE WHEN i.quantidade > 0 THEN i.valor_total_homologado / i.quantidade END vu,
       i.itens_lotes lote
  FROM itens_licitacoes i JOIN licitacoes l ON l.id_licitacao = i.id_licitacao WHERE i.id_item = :i""",
    "atas": """
SELECT 'atas' origem, a.inicio_validade dt, a.numero_ata ref, a.id_ata chave, a.unidade_gerenciadora unidade,
       i.fornecedor, i.cnpj_norm, i.qtd, NULL un, i.vl_unitario vu, NULL lote
  FROM itens_atas_registro_preco i JOIN atas_registro_preco a ON a.id_ata = i.id_ata WHERE i.id_item = :i""",
}


def _uniao(origens) -> str:
    return "\nUNION ALL\n".join(_RAMOS[o] for o in origens)


def _registros(conn, id_item, origens, limite, offset) -> list[dict]:
    sql = (f"SELECT * FROM ({_uniao(origens)}\n) "
           "ORDER BY dt DESC NULLS LAST, origem, ref DESC LIMIT :lim OFFSET :off")
    cur = conn.execute(sql, {"i": id_item, "lim": limite, "off": offset})
    nomes = [d[0] for d in cur.description]
    linhas = [dict(zip(nomes, r)) for r in cur.fetchall()]
    for r in linhas:  # zero no banco não é preço nem quantidade: vira vazio, nunca "R$ 0,00"
        for k in ("qtd", "vu"):
            if not (isinstance(r[k], (int, float)) and r[k] > 0):
                r[k] = None
        r["fornecedor_mais"] = 0
        if r["origem"] == "licitacoes":
            r["fornecedor"], r["cnpj_norm"], r["fornecedor_mais"] = _comum.vencedor(conn, r["chave"], id_item, r["lote"])
    return linhas


def _ultimo_preco(conn, id_item, origens) -> dict | None:
    sql = (f"SELECT * FROM ({_uniao(origens)}\n) "
           "WHERE vu > 0 AND substr(dt, 1, 10) <= :hoje ORDER BY dt DESC LIMIT 1")
    cur = conn.execute(sql, {"i": id_item, "hoje": date.today().isoformat()})
    r = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], r)) if r else None


def get(conn, id_item, origem=None, pagina=1):
    r = conn.execute("SELECT * FROM catalogo WHERE id_item = ?", (id_item,)).fetchone()
    if not r:
        return None
    item = dict(r)
    contagens = {o: n for o, n in conn.execute(_CONTAGEM, {"i": id_item}).fetchall()}
    total = sum(contagens.values())
    com_dado = [o for o in ORIGENS if contagens.get(o)]
    # origem inválida ou sem registros vale como "Todos" (a aba nem existe)
    if origem not in com_dado:
        origem = None
    ctx = {"item": item, "contagens": contagens, "total": total, "origem": origem,
           "origens": com_dado, "rotulos_origem": ROTULO_ORIGEM, "linhas": [], "ultimo": None,
           "pag": _comum.paginar(0, 1)}
    if not total:
        return ctx
    selecionadas = [origem] if origem else com_dado
    pag = _comum.paginar(contagens[origem] if origem else total, pagina)
    ctx["pag"] = pag
    ctx["linhas"] = _registros(conn, id_item, selecionadas, pag["por_pagina"], pag["offset"])
    ctx["ultimo"] = _ultimo_preco(conn, id_item, com_dado)
    return ctx


def secao(conn, id_item, nome, pagina):
    return None  # item não tem seções; usa paginação na própria página
