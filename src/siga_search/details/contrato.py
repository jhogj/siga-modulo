"""Detalhe: contrato — /siga/contratos/{contratacao} e as listas completas de itens e notas."""
from __future__ import annotations

from . import _comum

SECOES = ("itens", "notas")

# Rótulo usado no h1 do modo seção, na trilha e no <caption> das tabelas.
TITULOS = {"itens": "Itens contratados", "notas": "Notas de autorização de despesa"}


def _base(conn, contratacao):
    if not contratacao:
        return None
    r = conn.execute("SELECT * FROM contratos WHERE contratacao = ?", (str(contratacao).strip(),)).fetchone()
    return dict(r) if r else None


def _licitacao(conn, id_licitacao):
    if id_licitacao is None:
        return None
    r = conn.execute(
        "SELECT id_licitacao, licitacao, modalidade, unidade, status, dt_homologacao, valor_total_homologado "
        "FROM licitacoes WHERE id_licitacao = ?", (id_licitacao,)).fetchone()
    return dict(r) if r else None


def _compra(conn, id_processo, processo_norm):
    """Compra de origem: compras_diretas e, se vazio, outras_compras (agregado por processo).

    A tabela não tem índice em id_processo; quando o contrato traz o processo, a busca passa antes
    pelo índice de processo_norm (com e sem o prefixo "**") e só cai na varredura se não achar.
    """
    if id_processo is None:
        return None
    campos = ("SELECT id_processo, max(processo) processo, max(afastamento) afastamento, max(unidade) unidade, "
              "max(dt_aprovacao) dt, max(valor_processo) valor FROM {t} WHERE id_processo = ?")
    for tabela in ("compras_diretas", "outras_compras"):
        r = None
        if processo_norm:
            r = conn.execute(campos.format(t=tabela) + " AND processo_norm IN (?, '**' || ?)",
                             (id_processo, processo_norm, processo_norm)).fetchone()
        if not r or r["id_processo"] is None:
            r = conn.execute(campos.format(t=tabela), (id_processo,)).fetchone()
        if r and r["id_processo"] is not None:
            return dict(r)
    return None


def _atas(conn, contratacao):
    rows = conn.execute(
        "SELECT a.id_ata, a.numero_ata, a.unidade_gerenciadora, a.status_ata, a.fim_validade "
        "FROM atas_registro_preco a WHERE a.id_ata IN "
        "(SELECT DISTINCT id_ata FROM itens_contratos WHERE contratacao = ? AND id_ata IS NOT NULL) "
        "ORDER BY a.fim_validade DESC, a.numero_ata", (contratacao,)).fetchall()
    return [dict(r) for r in rows]


def _total_itens(conn, contratacao) -> int:
    return conn.execute("SELECT count(*) FROM itens_contratos WHERE contratacao = ?", (contratacao,)).fetchone()[0]


def _positivo(v):
    """Zero no banco não é preço nem quantidade: vira vazio, nunca "R$ 0,00", como nas
    páginas de item, licitação, compra e ata."""
    return v if isinstance(v, (int, float)) and v > 0 else None


def _reais(v):
    """Valor em R$ que arredonda para zero (0,0001 em 2024008355) também fica vazio."""
    return v if isinstance(v, (int, float)) and round(v, 2) > 0 else None


def _itens(conn, contratacao, limite, offset=0):
    # ata_ok vem do LEFT JOIN: id_ata de itens_contratos sem ata em atas_registro_preco (145 linhas)
    # não vira link, que levaria a um 404 (princípio 5: link só quando a chave existe).
    rows = conn.execute(
        "SELECT i.id_item, i.item, i.qtd_original, i.vl_unit_original, i.total_aditivada_suprimida, i.id_ata, "
        "a.id_ata AS ata_ok, a.numero_ata FROM itens_contratos i LEFT JOIN atas_registro_preco a ON a.id_ata = i.id_ata "
        "WHERE i.contratacao = ? ORDER BY i.item, i.rowid LIMIT ? OFFSET ?",
        (contratacao, limite, offset)).fetchall()
    saida = []
    for r in rows:
        d = dict(r)
        q, u = _positivo(d["qtd_original"]), _positivo(d["vl_unit_original"])
        d["total"] = _reais(q * u) if (q is not None and u is not None) else None
        d["qtd_original"], d["vl_unit_original"] = q, _reais(u)
        saida.append(d)
    return saida


# As notas vêm repetidas no acompanhamento (uma linha por fonte de recurso/evento: 4.884 linhas
# para 222 notas no contrato 2019006174). Fonte e valor ficam de fora, então a nota é contada e
# listada uma vez só (princípio 3 e proibição 16).
_NOTAS = ("SELECT DISTINCT chave_siga, dt_emissao_nadsiga, ano, natureza FROM acompanhamento_assapc "
          "WHERE contratacao = ?")


def _total_notas(conn, contratacao) -> int:
    return conn.execute(f"SELECT count(*) FROM ({_NOTAS})", (contratacao,)).fetchone()[0]


def _notas(conn, contratacao, limite, offset=0):
    rows = conn.execute(
        f"SELECT * FROM ({_NOTAS}) ORDER BY dt_emissao_nadsiga DESC NULLS LAST, chave_siga DESC "
        "LIMIT ? OFFSET ?", (contratacao, limite, offset)).fetchall()
    return [dict(r) for r in rows]


def _colunas_itens(itens) -> dict:
    """Colunas opcionais da tabela de itens: só existem se alguma linha visível tem o dado."""
    return {
        "qtd": any(i["qtd_original"] is not None for i in itens),
        "unitario": any(i["vl_unit_original"] is not None for i in itens),
        "total": any(i["total"] is not None for i in itens),
        "ata": any(i["ata_ok"] is not None for i in itens),
        "aditivo": any(i["total_aditivada_suprimida"] not in (None, 0) for i in itens),
    }


def _colunas_notas(notas) -> dict:
    """Emissão só existe se alguma nota visível tem data válida."""
    from ..fmt import data  # import local: fmt importa details._comum, e o pacote importa este módulo
    return {"emissao": any(data(n["dt_emissao_nadsiga"]) for n in notas)}


def get(conn, contratacao):
    c = _base(conn, contratacao)
    if not c:
        return None
    chave = c["contratacao"]
    n_itens = _total_itens(conn, chave)
    n_notas = _total_notas(conn, chave)
    itens = _itens(conn, chave, _comum.corte(n_itens))
    notas = _notas(conn, chave, _comum.corte(n_notas))
    return {
        "contrato": c,
        "licitacao": _licitacao(conn, c["id_licitacao"]),
        "compra": _compra(conn, c["id_processo"], c["processo_norm"]),
        "atas": _atas(conn, chave),
        "itens": itens,
        "n_itens": n_itens,
        "colunas": _colunas_itens(itens),
        "notas": notas,
        "n_notas": n_notas,
        "colunas_notas": _colunas_notas(notas),
    }


def secao(conn, contratacao, nome, pagina):
    if nome not in SECOES:
        return None
    c = _base(conn, contratacao)
    if not c:
        return None
    chave = c["contratacao"]
    total = _total_itens(conn, chave) if nome == "itens" else _total_notas(conn, chave)
    if not total:  # seção sem linhas não existe: 404, como nas demais páginas
        return None
    pag = _comum.paginar(total, pagina)
    if nome == "itens":
        linhas = _itens(conn, chave, pag["por_pagina"], pag["offset"])
        colunas = _colunas_itens(linhas)
    else:
        linhas = _notas(conn, chave, pag["por_pagina"], pag["offset"])
        colunas = _colunas_notas(linhas)
    return {"contrato": c, "titulo_secao": TITULOS[nome], "linhas": linhas, "pag": pag, "colunas": colunas}
