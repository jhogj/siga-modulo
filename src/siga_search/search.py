"""Busca do SIGA: MATCH, filtros, contagens, facetas, hidratação e correspondência exata."""
from __future__ import annotations

import re
import sqlite3
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import date

from .db import get_conn
from .details._comum import POR_PAGINA, paginar
from .normalize import processo_norm
from .regras import (
    ATA_INTERROMPIDAS, CANCELADOS, LIC_CANCELADAS, LIC_HOMOLOGADAS, LIC_SEM_VENCEDOR, LIC_SUSPENSAS,
    SITUACOES, TRAMITACAO,
)

TIPOS = {  # ordem = ordem das abas e dos grupos de "Tudo"
    "contratos":    {"fts": "fts_contrato",   "rotulo": "Contratos",    "sing": "contrato",   "plur": "contratos",    "genero": "m", "periodo": True,  "orgao": True},
    "fornecedores": {"fts": "fts_fornecedor", "rotulo": "Fornecedores", "sing": "fornecedor", "plur": "fornecedores", "genero": "m", "periodo": False, "orgao": False},
    "licitacoes":   {"fts": "fts_licitacao",  "rotulo": "Licitações",   "sing": "licitação",  "plur": "licitações",   "genero": "f", "periodo": True,  "orgao": True},
    "atas":         {"fts": "fts_ata",        "rotulo": "Atas",         "sing": "ata",        "plur": "atas",         "genero": "f", "periodo": True,  "orgao": True},
    "compras":      {"fts": "fts_compra",     "rotulo": "Compras",      "sing": "compra",     "plur": "compras",      "genero": "f", "periodo": True,  "orgao": True},
    "itens":        {"fts": "fts_item",       "rotulo": "Itens",        "sing": "item",       "plur": "itens",        "genero": "m", "periodo": False, "orgao": False},
}
ORDEM_PADRAO = {"contratos": "recentes", "fornecedores": "relevancia", "licitacoes": "recentes",
                "atas": "recentes", "compras": "recentes", "itens": "relevancia"}
ORDENS = {"contratos": [("recentes", "Mais recentes"), ("valor", "Maior valor")],
          "fornecedores": [("relevancia", "Mais relevantes"), ("recentes", "Mais recentes")],
          "licitacoes": [("recentes", "Mais recentes"), ("valor", "Maior valor")],
          "atas": [("recentes", "Mais recentes")],
          "compras": [("recentes", "Mais recentes"), ("valor", "Maior valor")],
          "itens": [("relevancia", "Mais relevantes"), ("recentes", "Mais recentes")]}

# Chaves que saem do FTS por tipo (compras é agrupada à parte).
_CHAVES = {"contratos": "f.contratacao", "fornecedores": "f.cnpj_norm", "licitacoes": "f.id_licitacao",
           "atas": "f.id_ata", "itens": "f.id_item, f.dt"}

_TOKEN = re.compile(r"[A-Za-zÀ-ÿ0-9]+")
_JOIN_C = "JOIN contratos c ON c.codigo_contrato = f.codigo_contrato"
_JOIN_L = "JOIN licitacoes l ON l.id_licitacao = f.id_licitacao"


def _lista(valores) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in valores)


def _hoje() -> str:
    return date.today().isoformat()


# Situação: tipo -> chave -> (fragmento SQL, join necessário ou None)
_SITUACAO_SQL = {
    "contratos": {
        "vigentes": (f"c.status_contratacao NOT IN ({_lista(CANCELADOS + TRAMITACAO + ('Encerrado',))}) "
                     "AND c.dt_fim_vigencia >= :hoje", _JOIN_C),
        "encerrados": (f"c.status_contratacao NOT IN ({_lista(CANCELADOS + TRAMITACAO)}) "
                       "AND (c.status_contratacao = 'Encerrado' OR c.dt_fim_vigencia < :hoje)", _JOIN_C),
        "tramitacao": (f"f.status IN ({_lista(TRAMITACAO)})", None),
        "cancelados": (f"f.status IN ({_lista(CANCELADOS)})", None),
    },
    "licitacoes": {
        "homologadas": (f"f.status IN ({_lista(LIC_HOMOLOGADAS)})", None),
        "andamento": (f"f.status NOT IN ({_lista(LIC_HOMOLOGADAS + LIC_SEM_VENCEDOR + LIC_CANCELADAS + LIC_SUSPENSAS)})", None),
        "sem_vencedor": (f"f.status IN ({_lista(LIC_SEM_VENCEDOR)})", None),
        "canceladas": (f"f.status IN ({_lista(LIC_CANCELADAS)})", None),
        "suspensas": (f"f.status IN ({_lista(LIC_SUSPENSAS)})", None),
    },
    "atas": {
        "vigentes": (f"f.dt >= :hoje AND f.status NOT IN ({_lista(ATA_INTERROMPIDAS)})", None),
        "encerradas": (f"f.dt < :hoje AND f.status NOT IN ({_lista(ATA_INTERROMPIDAS)})", None),
        "interrompidas": (f"f.status IN ({_lista(ATA_INTERROMPIDAS)})", None),
    },
    "fornecedores": {
        "sancao": ("EXISTS (SELECT 1 FROM sancoes s WHERE s.cnpj_norm = f.cnpj_norm AND s.status = 'Vigente' "
                   "AND (s.dt_final IS NULL OR s.dt_final >= :hoje))", None),
        "bloqueados": ("f.situacao = 'Bloqueado'", None),
        "penalizados": ("f.situacao = 'Penalizado'", None),
    },
    "compras": {
        "diretas": ("f.src = 'compras_diretas'", None),
        "outras": ("f.src = 'outras_compras'", None),
    },
    "itens": {
        "material": ("f.tipo = 'MATERIAL'", None),
        "servico": ("f.tipo = 'SERVICOS'", None),
    },
}
assert all(set(_SITUACAO_SQL[t]) == {k for k, _ in SITUACOES[t]["opcoes"]} for t in SITUACOES)


# ---------------------------------------------------------------------------
# MATCH e filtros
# ---------------------------------------------------------------------------

def build_match(q: str) -> str | None:
    """Converte a consulta em MATCH FTS5 seguro.

    CNPJ (14 dígitos, com ou sem máscara) vira a frase dos grupos 2-3-3-4-2, porque o FTS
    tokenizou o CNPJ mascarado. Senão, tokens com prefixo: 'cartucho hp' -> '"cartucho"* "hp"*'.

    Token de 1 caractere vai sem prefixo ('vitamina c' -> '"vitamina"* "c"'): "c"* expande para
    todo termo iniciado por c (casa "complexo", não "vitamina C") e custa até 5 s. Tokens repetidos
    saem uma vez só (o AND é idempotente).
    """
    compacto = re.sub(r"[\s./-]", "", q or "")
    if re.fullmatch(r"\d{14}", compacto):
        c = compacto
        return f'"{c[:2]} {c[2:5]} {c[5:8]} {c[8:12]} {c[12:]}"'
    tokens = list(dict.fromkeys(t.lower() for t in _TOKEN.findall(q or "")))
    if not tokens:
        return None
    return " ".join(f'"{t}"' if len(t) == 1 else f'"{t}"*' for t in tokens)


def situacao_valida(tipo: str, situacao: str | None) -> str | None:
    return situacao if situacao in _SITUACAO_SQL.get(tipo, {}) else None


def ordem_valida(tipo: str, ordem: str | None) -> str:
    return ordem if ordem in dict(ORDENS[tipo]) else ORDEM_PADRAO[tipo]


def _where(tipo: str, match: str, filtros: dict, *, com_situacao: bool, com_orgao: bool = True):
    t = TIPOS[tipo]
    partes = [f"f.{t['fts']} MATCH :m"]
    params = {"m": match, "hoje": _hoje()}
    joins: list[str] = []
    if t["periodo"]:
        if filtros.get("de"):
            partes.append("substr(f.dt, 1, 10) >= :de")
            params["de"] = filtros["de"]
        if filtros.get("ate"):
            partes.append("substr(f.dt, 1, 10) <= :ate")
            params["ate"] = filtros["ate"]
    if t["orgao"] and com_orgao and filtros.get("orgao"):
        partes.append("f.unidade = :orgao")
        params["orgao"] = filtros["orgao"]
    sit = situacao_valida(tipo, filtros.get("situacao")) if com_situacao else None
    if sit:
        frag, join = _SITUACAO_SQL[tipo][sit]
        partes.append(frag)
        if join:
            joins.append(join)
    return " AND ".join(partes), params, joins


def _from(tipo: str, joins: list[str]) -> str:
    j = " ".join(dict.fromkeys(joins))
    return f"FROM {TIPOS[tipo]['fts']} f {j}".rstrip()


# ---------------------------------------------------------------------------
# Contagens, páginas e facetas
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Cache e paralelismo. O banco é somente leitura: contagens podem ser memorizadas
# (a chave inclui a data, por causa das situações que dependem de "hoje").
# ---------------------------------------------------------------------------

_CACHE: OrderedDict = OrderedDict()
_CACHE_MAX = 512
_TRAVA = threading.Lock()


def _memo(chave, calcular):
    with _TRAVA:
        if chave in _CACHE:
            _CACHE.move_to_end(chave)
            return _CACHE[chave]
    valor = calcular()
    with _TRAVA:
        _CACHE[chave] = valor
        while len(_CACHE) > _CACHE_MAX:
            _CACHE.popitem(last=False)
    return valor


def _chave(*partes, filtros: dict):
    return (*partes, filtros.get("de"), filtros.get("ate"), filtros.get("orgao"), _hoje())


def em_paralelo(*tarefas):
    """Roda cada tarefa(conn) numa conexão própria, em paralelo; devolve os resultados na ordem."""
    def rodar(tarefa):
        with closing(get_conn()) as c:
            return tarefa(c)
    if len(tarefas) == 1:
        return [rodar(tarefas[0])]
    with ThreadPoolExecutor(max_workers=len(tarefas)) as ex:
        return list(ex.map(rodar, tarefas))


def contar(conn: sqlite3.Connection, tipo: str, match: str, filtros: dict, com_situacao: bool = True) -> int:
    sit = situacao_valida(tipo, filtros.get("situacao")) if com_situacao else None
    chave = _chave("n", tipo, match, sit, filtros=filtros)
    return _memo(chave, lambda: _contar(conn, tipo, match, filtros, com_situacao))


def _contar(conn, tipo: str, match: str, filtros: dict, com_situacao: bool) -> int:
    where, params, joins = _where(tipo, match, filtros, com_situacao=com_situacao)
    if tipo == "compras":
        sql = f"SELECT count(*) FROM (SELECT 1 {_from(tipo, joins)} WHERE {where} GROUP BY f.src, f.processo)"
    else:
        sql = f"SELECT count(*) {_from(tipo, joins)} WHERE {where}"
    return conn.execute(sql, params).fetchone()[0]


def _pagina_chaves(conn, tipo: str, match: str, filtros: dict, ordem: str, limite: int, offset: int):
    where, params, joins = _where(tipo, match, filtros, com_situacao=True)
    params.update(lim=limite, off=offset)
    if tipo == "compras":
        ordem_sql = "ORDER BY max(CAST(f.valor AS REAL)) DESC" if ordem == "valor" else "ORDER BY dt DESC"
        sql = (f"SELECT f.src, f.processo, min(CAST(f.src_id AS INTEGER)) AS src_id, max(f.dt) AS dt "
               f"{_from(tipo, joins)} WHERE {where} GROUP BY f.src, f.processo {ordem_sql} LIMIT :lim OFFSET :off")
        return [(r["src"], r["src_id"]) for r in conn.execute(sql, params)]
    if ordem == "relevancia":
        ordem_sql = "ORDER BY f.rank"
    elif ordem == "valor" and tipo == "contratos":
        joins.append(_JOIN_C)
        ordem_sql = "ORDER BY c.valor_total_contrato DESC NULLS LAST"
    elif ordem == "valor" and tipo == "licitacoes":
        joins.append(_JOIN_L)
        ordem_sql = "ORDER BY coalesce(l.valor_total_homologado, l.valor_total_estimado) DESC NULLS LAST"
    else:
        ordem_sql = "ORDER BY f.dt DESC NULLS LAST"
    sql = f"SELECT {_CHAVES[tipo]} {_from(tipo, joins)} WHERE {where} {ordem_sql} LIMIT :lim OFFSET :off"
    rows = conn.execute(sql, params).fetchall()
    if tipo == "itens":
        return [(r[0], r[1]) for r in rows]
    return [r[0] for r in rows]


def buscar(conn: sqlite3.Connection, tipo: str, match: str, filtros: dict, pagina: int = 1):
    """Uma página (25 linhas) do tipo, com todos os filtros. Devolve (linhas, total)."""
    total = contar(conn, tipo, match, filtros, com_situacao=True)
    if not total:
        return [], 0
    pag = paginar(total, pagina, POR_PAGINA)
    ordem = ordem_valida(tipo, filtros.get("ordem"))
    sit = situacao_valida(tipo, filtros.get("situacao"))
    chave = _chave("pagina", tipo, match, sit, ordem, pag["offset"], filtros=filtros)
    chaves = _memo(chave, lambda: _pagina_chaves(conn, tipo, match, filtros, ordem, POR_PAGINA, pag["offset"]))
    return hidratar(conn, tipo, chaves), total


def contagens(conn: sqlite3.Connection, match: str, filtros: dict) -> dict[str, int]:
    """Contagem por tipo para as abas: período e órgão, sem situação (tipos em paralelo, com cache)."""
    base = {k: v for k, v in filtros.items() if k in ("de", "ate", "orgao")}
    with _TRAVA:
        prontos = {t: _CACHE[k] for t in TIPOS if (k := _chave("n", t, match, None, filtros=base)) in _CACHE}
    faltam = [t for t in TIPOS if t not in prontos]
    if faltam:
        valores = em_paralelo(*(lambda c, t=t: contar(c, t, match, base, com_situacao=False) for t in faltam))
        prontos.update(zip(faltam, valores))
    return {t: prontos[t] for t in TIPOS}


def _previa(conn, tipo: str, match: str, filtros: dict, n: int):
    """(total sem situação, chaves das n primeiras linhas na ordem padrão)."""
    chave = _chave("previa", tipo, match, n, filtros=filtros)

    def calcular():
        if tipo == "compras":  # total e página numa só passada pelo GROUP BY
            where, params, joins = _where(tipo, match, filtros, com_situacao=False)
            sql = (f"SELECT src, src_id, count(*) OVER () AS total FROM (SELECT f.src, f.processo, "
                   f"min(CAST(f.src_id AS INTEGER)) AS src_id, max(f.dt) AS dt {_from(tipo, joins)} WHERE {where} "
                   f"GROUP BY f.src, f.processo) ORDER BY dt DESC LIMIT {int(n)}")
            rows = conn.execute(sql, params).fetchall()
            total = rows[0]["total"] if rows else 0
            _memo(_chave("n", tipo, match, None, filtros=filtros), lambda: total)
            return total, [(r["src"], r["src_id"]) for r in rows]
        total = contar(conn, tipo, match, filtros, com_situacao=False)
        return total, (_pagina_chaves(conn, tipo, match, filtros, ORDEM_PADRAO[tipo], n, 0) if total else [])
    return _memo(chave, calcular)


def visao_geral(conn: sqlite3.Connection, match: str, filtros: dict, contagens_: dict | None = None):
    """Aba "Tudo": {tipo: (3 primeiras linhas, total)}, na ordem padrão de cada tipo; omite total 0.

    Os tipos rodam em paralelo; `contagens_`, se vier, evita trabalho para tipos com total 0.
    """
    base = {k: v for k, v in filtros.items() if k in ("de", "ate", "orgao")}
    tipos = [t for t in TIPOS if contagens_ is None or contagens_.get(t)]
    previas = em_paralelo(*(lambda c, t=t: _previa(c, t, match, base, 3) for t in tipos)) if tipos else []
    saida = {}
    for t, (total, chaves) in zip(tipos, previas):
        if total:
            saida[t] = (hidratar(conn, t, chaves)[:3], total)
    return saida


def facetas_orgao(conn: sqlite3.Connection, tipo: str, match: str, filtros: dict) -> list[tuple[str, int]]:
    """Órgãos com resultado (período e situação aplicados, sem o próprio órgão), em ordem alfabética."""
    if not TIPOS[tipo]["orgao"]:
        return []
    where, params, joins = _where(tipo, match, filtros, com_situacao=True, com_orgao=False)
    n = "count(DISTINCT f.src || '|' || f.processo)" if tipo == "compras" else "count(*)"
    sql = (f"SELECT f.unidade, {n} {_from(tipo, joins)} WHERE {where} AND f.unidade IS NOT NULL "
           f"AND f.unidade <> '' GROUP BY f.unidade ORDER BY f.unidade")
    chave = ("facetas", tipo, match, situacao_valida(tipo, filtros.get("situacao")),
             filtros.get("de"), filtros.get("ate"), _hoje())
    return _memo(chave, lambda: [(r[0], r[1]) for r in conn.execute(sql, params)])


def facetas_orgao_tudo(conn: sqlite3.Connection, match: str, filtros: dict) -> list[tuple[str, int]]:
    """Aba "Tudo": soma, por órgão, os resultados de contratos, licitações, atas e compras."""
    tipos = [t for t, cfg in TIPOS.items() if cfg["orgao"]]
    base = {k: v for k, v in filtros.items() if k in ("de", "ate")}
    soma: dict[str, int] = {}
    for facetas in em_paralelo(*(lambda c, t=t: facetas_orgao(c, t, match, base) for t in tipos)):
        for u, n in facetas:
            soma[u] = soma.get(u, 0) + n
    return list(soma.items())


_ORGAOS: list[str] | None = None


def orgaos(conn: sqlite3.Connection) -> list[str]:
    """Todos os órgãos (unidades) do SIGA, em ordem alfabética. Calculado uma vez por processo."""
    global _ORGAOS
    if _ORGAOS is None:
        sql = ("SELECT u FROM (SELECT unidade u FROM contratos UNION SELECT unidade FROM licitacoes "
               "UNION SELECT unidade FROM compras_diretas UNION SELECT unidade FROM outras_compras "
               "UNION SELECT unidade_gerenciadora FROM atas_registro_preco) "
               "WHERE u IS NOT NULL AND trim(u) <> '' ORDER BY u")
        _ORGAOS = [r[0] for r in conn.execute(sql)]
    return _ORGAOS


# ---------------------------------------------------------------------------
# Hidratação
# ---------------------------------------------------------------------------

def _marcas(n: int) -> str:
    return ", ".join("?" * n)


def _por_chave(rows, chave: str) -> dict:
    return {r[chave]: dict(r) for r in rows}


def _compras_por_processo(conn, src: str, ids: list) -> dict:
    if not ids:
        return {}
    sql = (f"SELECT id_processo, max(processo) processo, max(unidade) unidade, max(objeto) objeto, "
           f"max(afastamento) afastamento, max(dt_aprovacao) dt, max(valor_processo) valor, count(*) n_itens, "
           f"count(DISTINCT coalesce(cnpj_norm, fornecedor_vencedor)) n_fornecedores, "
           f"min(fornecedor_vencedor) fornecedor FROM {src} WHERE id_processo IN ({_marcas(len(ids))}) "
           f"GROUP BY id_processo")
    return _por_chave(conn.execute(sql, ids), "id_processo")


def hidratar(conn: sqlite3.Connection, tipo: str, chaves: list) -> list[dict]:
    """Linhas completas para exibição, na ordem de `chaves`; cada dict leva "tipo"."""
    if not chaves:
        return []
    hoje = _hoje()
    if tipo == "contratos":
        rows = conn.execute(
            "SELECT contratacao, objeto, fornecedor, cnpj_norm, unidade, dt_contratacao AS dt, "
            "status_contratacao AS status, dt_fim_vigencia AS dt_fim, valor_total_contrato AS valor "
            f"FROM contratos WHERE contratacao IN ({_marcas(len(chaves))})", [str(c) for c in chaves])
        m = _por_chave(rows, "contratacao")
        linhas = [m.get(str(c)) for c in chaves]
    elif tipo == "fornecedores":
        ph = _marcas(len(chaves))
        m = _por_chave(conn.execute(
            f"SELECT cnpj_norm, cpf_cnpj, nome, cidade, uf, situacao FROM fornecedores WHERE cnpj_norm IN ({ph})",
            chaves), "cnpj_norm")
        agg = {r[0]: (r[1], r[2]) for r in conn.execute(
            f"SELECT cnpj_norm, count(*) n, sum(valor_total_contrato) v FROM contratos WHERE cnpj_norm IN ({ph}) "
            f"AND status_contratacao NOT IN ({_lista(CANCELADOS)}) GROUP BY cnpj_norm", chaves)}
        sanc = {r[0] for r in conn.execute(
            f"SELECT DISTINCT cnpj_norm FROM sancoes WHERE cnpj_norm IN ({ph}) AND status = 'Vigente' "
            "AND (dt_final IS NULL OR dt_final >= ?)", [*chaves, hoje])}
        linhas = []
        for c in chaves:
            d = m.get(c)
            if d:
                n, v = agg.get(c, (0, None))
                d.update(n_contratos=n, valor=v, sancao_vigente=c in sanc)
            linhas.append(d)
    elif tipo == "licitacoes":
        ids = [int(c) for c in chaves]
        m = _por_chave(conn.execute(
            "SELECT id_licitacao, licitacao, modalidade, unidade, objeto, status, "
            "valor_total_homologado AS valor_homologado, valor_total_estimado AS valor_estimado, "
            f"coalesce(dt_homologacao, dt_publicacao) AS dt FROM licitacoes WHERE id_licitacao IN ({_marcas(len(ids))})",
            ids), "id_licitacao")
        linhas = [m.get(i) for i in ids]
    elif tipo == "atas":
        ids = [int(c) for c in chaves]
        ph = _marcas(len(ids))
        m = _por_chave(conn.execute(
            "SELECT id_ata, numero_ata, unidade_gerenciadora AS unidade, objeto, status_ata, fim_validade "
            f"FROM atas_registro_preco WHERE id_ata IN ({ph})", ids), "id_ata")
        forn = {r[0]: (r[1], r[2]) for r in conn.execute(
            f"SELECT id_ata, count(DISTINCT fornecedor) n, min(fornecedor) f FROM itens_atas_registro_preco "
            f"WHERE id_ata IN ({ph}) GROUP BY id_ata", ids)}
        linhas = []
        for i in ids:
            d = m.get(i)
            if d:
                n, f = forn.get(i, (0, None))
                d.update(n_fornecedores=n, fornecedor=f)
            linhas.append(d)
    elif tipo == "compras":
        por_src: dict[str, list[int]] = {}
        for src, src_id in chaves:
            por_src.setdefault(src, []).append(int(src_id))
        proc: dict[tuple, int] = {}
        grupos: dict[str, dict] = {}
        for src, rowids in por_src.items():
            if src not in ("compras_diretas", "outras_compras"):
                continue
            for r in conn.execute(f"SELECT rowid, id_processo FROM {src} WHERE rowid IN ({_marcas(len(rowids))})", rowids):
                proc[(src, r[0])] = r[1]
            grupos[src] = _compras_por_processo(conn, src, sorted({proc[(src, i)] for i in rowids if (src, i) in proc}))
        linhas, vistos = [], set()
        for src, src_id in chaves:
            idp = proc.get((src, int(src_id)))
            if idp is None or idp in vistos:
                continue
            vistos.add(idp)
            linhas.append(grupos[src].get(idp))
    elif tipo == "itens":
        ids = [int(c[0]) for c in chaves]
        m = _por_chave(conn.execute(
            "SELECT id_item, cod_item, tipo AS tipo_catalogo, familia, classe, descricao FROM catalogo "
            f"WHERE id_item IN ({_marcas(len(ids))})", ids), "id_item")
        linhas = []
        for i, dt in ((int(c[0]), c[1]) for c in chaves):
            d = m.get(i)
            if d:
                d["dt"] = dt
            linhas.append(d)
    else:
        raise ValueError(tipo)
    return [d | {"tipo": tipo} for d in linhas if d]


# ---------------------------------------------------------------------------
# Correspondência exata
# ---------------------------------------------------------------------------

_RE_CNPJ = re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$")
_RE_CONTRATACAO = re.compile(r"^\d{10}$")
_RE_PROCESSO = re.compile(r"^(SEI|E)-\S+$", re.IGNORECASE)
_RE_CATALOGO = re.compile(r"^\d{4}\.\d{3}\.\d{4}$")
_LIMITE_EXATA = 5


def detectar(conn: sqlite3.Connection, q: str) -> list[dict]:
    """Registros cuja chave pública é exatamente `q` (CNPJ, contratação, processo, código de catálogo)."""
    q = (q or "").strip()
    if not q:
        return []
    if _RE_CNPJ.match(q):
        r = conn.execute("SELECT cnpj_norm FROM fornecedores WHERE cnpj_norm = ?", (re.sub(r"\D", "", q),)).fetchone()
        return hidratar(conn, "fornecedores", [r[0]]) if r else []
    if _RE_CONTRATACAO.match(q):
        rows = conn.execute("SELECT contratacao FROM contratos WHERE contratacao = ? LIMIT 1", (q,)).fetchall()
        return hidratar(conn, "contratos", [r[0] for r in rows])
    if _RE_CATALOGO.match(q):
        rows = conn.execute("SELECT id_item FROM catalogo WHERE cod_item = ? LIMIT ?", (q, _LIMITE_EXATA)).fetchall()
        return hidratar(conn, "itens", [(r[0], None) for r in rows])
    if _RE_PROCESSO.match(q):
        pn = processo_norm(q)
        saida: list[dict] = []
        consultas = (
            ("contratos", "SELECT contratacao FROM contratos WHERE processo_norm = ? ORDER BY dt_contratacao DESC LIMIT ?"),
            ("licitacoes", "SELECT id_licitacao FROM licitacoes WHERE processo_norm = ? LIMIT ?"),
            ("atas", "SELECT DISTINCT id_ata FROM ata_processos WHERE processo_norm = ? LIMIT ?"),  # qualquer processo da ata
        )
        for tipo, sql in consultas:
            restam = _LIMITE_EXATA - len(saida)
            if restam <= 0:
                break
            chaves = [r[0] for r in conn.execute(sql, (pn, restam))]
            saida += hidratar(conn, tipo, chaves)
        for src in ("compras_diretas", "outras_compras"):
            restam = _LIMITE_EXATA - len(saida)
            if restam <= 0:
                break
            ids = [r[0] for r in conn.execute(
                f"SELECT DISTINCT id_processo FROM {src} WHERE processo_norm IN (?, '**' || ?) LIMIT ?",
                (pn, pn, restam))]
            m = _compras_por_processo(conn, src, ids)
            saida += [m[i] | {"tipo": "compras"} for i in ids if i in m]
        return saida[:_LIMITE_EXATA]
    return []
