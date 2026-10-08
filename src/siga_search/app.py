"""FastAPI app — SIGA no Radar RJ: home, busca, detalhes, redirects legados e 404."""
from __future__ import annotations

import re
from contextlib import closing
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import details as D
from . import fmt, regras
from . import search as S
from .db import conexao, get_conn
from .details._comum import paginar

ROOT = Path(__file__).parent.parent.parent

app = FastAPI(title="Radar RJ · SIGA")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
TEMPLATES = Jinja2Templates(directory=ROOT / "templates")


def _extracao() -> str:
    try:
        with closing(get_conn()) as c:
            r = c.execute("SELECT data_extracao FROM contratos LIMIT 1").fetchone()
            return fmt.data(r[0]) if r else ""
    except Exception:  # banco ausente não impede o app de subir
        return ""


EXTRACAO = _extracao()
fmt.registrar(TEMPLATES.env, extracao=EXTRACAO)   # filtros, testes e globais Jinja

SECOES = {
    "contratos": ("itens", "notas"),
    "fornecedores": ("contratos", "compras", "licitacoes"),
    "licitacoes": ("participantes", "itens", "atas", "contratos"),
    "atas": ("itens", "contratos", "orgaos"),
    "compras": ("itens", "contratos"),
}
_DATA = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATA_BR = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
_ANO = re.compile(r"(19|20)[0-9]{2}")
_ID = re.compile(r"[0-9]{1,18}")  # só ASCII ("²" passa em isdigit) e cabe no INTEGER do SQLite


# ---------------------------------------------------------------------------
# Auxiliares
# ---------------------------------------------------------------------------

def _p(v: str | None) -> str | None:
    """Parâmetro com string vazia vale como ausente."""
    if v is None:
        return None
    v = v.strip()
    return v or None


def _pagina(v: str | None) -> int:
    try:
        return max(1, int(v)) if v else 1
    except ValueError:
        return 1


def _busca_ref(request: Request) -> dict | None:
    ref = request.headers.get("referer")
    if not ref:
        return None
    partes = urlsplit(ref)
    if partes.path != "/siga/busca":
        return None
    q = (parse_qs(partes.query).get("q") or [""])[0].strip()
    if not q:
        return None
    return {"q": q, "href": "/siga/busca?" + partes.query}


def _render(request: Request, template: str, ctx: dict, status_code: int = 200):
    return TEMPLATES.TemplateResponse(request, template, ctx, status_code=status_code)


def _nao_encontrado(request: Request):
    return _render(request, "pages/404.html", {}, status_code=404)


def _detalhe(request: Request, template: str, dados: dict | None, secao: str | None = None):
    if not dados:
        return _nao_encontrado(request)
    return _render(request, template, {**dados, "secao": secao, "busca": _busca_ref(request)})


def _int(v: str | None) -> int | None:
    return int(v) if v and _ID.fullmatch(v) else None


def _data(v: str | None) -> str | None:
    """Data que existe, em AAAA-MM-DD ou DD/MM/AAAA → AAAA-MM-DD; o resto é descartado."""
    if not v:
        return None
    if m := _DATA_BR.fullmatch(v):
        v = f"{m[3]}-{m[2]}-{m[1]}"
    if not _DATA.fullmatch(v):
        return None
    try:
        date.fromisoformat(v)
    except ValueError:
        return None
    return v


def anos_periodo() -> list[str]:
    """Anos oferecidos no filtro de período: o atual e os cinco anteriores."""
    a = date.today().year
    return [str(a - i) for i in range(6)]


def _periodo(periodo: str | None, de: str | None, ate: str | None) -> dict:
    """Resolve o filtro de período: "12m", um ano ("2025") ou datas livres (de/ate).

    Devolve {"periodo", "de", "ate", "rotulo"}; "rotulo" é o texto do botão quando há filtro.
    """
    hoje = date.today()
    if periodo == "12m":
        inicio = hoje.replace(year=hoje.year - 1) if not (hoje.month == 2 and hoje.day == 29) \
            else hoje.replace(year=hoje.year - 1, day=28)
        return {"periodo": "12m", "de": inicio.isoformat(), "ate": None, "rotulo": "Últimos 12 meses"}
    if periodo and _ANO.fullmatch(periodo):
        return {"periodo": periodo, "de": f"{periodo}-01-01", "ate": f"{periodo}-12-31", "rotulo": periodo}
    de, ate = _data(de), _data(ate)
    if de and ate and de > ate:
        de, ate = ate, de
    if not (de or ate):
        return {"periodo": None, "de": None, "ate": None, "rotulo": None}
    if de and ate:
        rotulo = f"{fmt.data(de)} a {fmt.data(ate)}"
    else:
        rotulo = f"A partir de {fmt.data(de)}" if de else f"Até {fmt.data(ate)}"
    return {"periodo": "personalizado", "de": de, "ate": ate, "rotulo": rotulo}


@app.exception_handler(StarletteHTTPException)
async def _http_erro(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return _nao_encontrado(request)
    return HTMLResponse(str(exc.detail), status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validacao(request: Request, exc: RequestValidationError):
    return _nao_encontrado(request)


# ---------------------------------------------------------------------------
# Home e busca
# ---------------------------------------------------------------------------

@app.get("/")
def raiz():
    return RedirectResponse("/siga", status_code=302)


@app.get("/siga", response_class=HTMLResponse)
def home(request: Request, conn=Depends(conexao)):
    ctx = {"orgaos": fmt.opcoes(S.orgaos(conn), orgao=True), "tipos": S.TIPOS, "anos": anos_periodo()}
    return _render(request, "pages/home.html", ctx)


def _filtros_ativos(tipo: str, filtros: dict) -> bool:
    if tipo != "tudo" and filtros.get("situacao"):
        return True
    usa_periodo = tipo == "tudo" or S.TIPOS[tipo]["periodo"]
    return usa_periodo and any(filtros.get(k) for k in ("de", "ate", "orgao"))


@app.get("/siga/busca", response_class=HTMLResponse)
def busca(request: Request, q: str | None = None, tipo: str | None = None, periodo: str | None = None,
          de: str | None = None, ate: str | None = None, orgao: str | None = None,
          situacao: str | None = None, ordem: str | None = None, pagina: str | None = None,
          conn=Depends(conexao)):
    q = (q or "").strip()
    match = S.build_match(q)
    if not match:
        return RedirectResponse("/siga", status_code=302)
    tipo = tipo if tipo in S.TIPOS else "tudo"
    per = _periodo(_p(periodo), _p(de), _p(ate))
    filtros = {"periodo": per["periodo"], "de": per["de"], "ate": per["ate"], "orgao": _p(orgao)}
    if tipo != "tudo":
        filtros["situacao"] = S.situacao_valida(tipo, _p(situacao))
        filtros["ordem"] = S.ordem_valida(tipo, _p(ordem))

    pag_atual = _pagina(pagina)
    grupos, linhas, total, facetas = {}, [], 0, []
    if tipo == "tudo":  # prévias primeiro: cada tipo conta e pagina na mesma tarefa; as contagens saem do cache
        grupos = S.visao_geral(conn, match, filtros)
        contagens, exatas = S.contagens(conn, match, filtros), S.detectar(conn, q)
        facetas = S.facetas_orgao_tudo(conn, match, filtros)
    else:  # contagens das abas, página e facetas em paralelo, cada uma na sua conexão
        contagens, (linhas, total), facetas, exatas = S.em_paralelo(
            lambda c: S.contagens(c, match, filtros),
            lambda c: S.buscar(c, tipo, match, filtros, pag_atual),
            lambda c: S.facetas_orgao(c, tipo, match, filtros) if S.TIPOS[tipo]["orgao"] else [],
            lambda c: S.detectar(c, q))
    abas = [{"slug": "tudo", "rotulo": "Tudo", "n": None,
             "href": fmt.url_with(request, tipo="tudo", pagina=None, situacao=None, ordem=None)}]
    abas += [{"slug": t, "rotulo": cfg["rotulo"], "n": contagens[t],
              "href": fmt.url_with(request, tipo=t, pagina=None, situacao=None, ordem=None)}
             for t, cfg in S.TIPOS.items()]

    ctx = {
        "q": q, "tipo": tipo, "cfg": S.TIPOS.get(tipo), "filtros": filtros, "contagens": contagens,
        "total_geral": sum(contagens.values()), "abas": abas, "tipos": S.TIPOS,
        "exatas": exatas, "filtros_ativos": _filtros_ativos(tipo, filtros),
        "limpar_href": fmt.url_with(request, periodo=None, de=None, ate=None, orgao=None, situacao=None,
                                    ordem=None, pagina=None),
        "anos": anos_periodo(), "periodo_rotulo": per["rotulo"],
        "grupos": grupos, "linhas": linhas, "total": total, "pag": None, "orgaos": [], "situacoes": None,
        "ordens": None,
    }
    if tipo != "tudo":
        ctx.update(pag=paginar(total, pag_atual), situacoes=regras.SITUACOES[tipo], ordens=S.ORDENS[tipo])
    if tipo == "tudo" or S.TIPOS[tipo]["orgao"]:
        # Mais resultados primeiro; o órgão escolhido aparece sempre, mesmo com 0.
        facetas = sorted(facetas, key=lambda f: (-f[1], f[0]))
        if filtros["orgao"] and filtros["orgao"] not in {u for u, _ in facetas}:
            facetas = [(filtros["orgao"], 0)] + facetas
        ctx["orgaos"] = fmt.opcoes(facetas, orgao=True)
    return _render(request, "pages/busca.html", ctx)


@app.get("/api/search")
def api_search(q: str | None = None, tipo: str | None = None, pagina: str | None = None, conn=Depends(conexao)):
    q = (q or "").strip()
    match = S.build_match(q)
    if not match:
        return JSONResponse({"q": q, "tipo": tipo, "total": 0, "resultados": []})
    if tipo in S.TIPOS:
        linhas, total = S.buscar(conn, tipo, match, {}, _pagina(pagina))
    else:
        tipo = "tudo"
        cont = S.contagens(conn, match, {})
        linhas = [r for ls, _ in S.visao_geral(conn, match, {}, cont).values() for r in ls]
        total = sum(cont.values())
    return {"q": q, "tipo": tipo, "total": total, "resultados": linhas}


# ---------------------------------------------------------------------------
# Detalhes
# ---------------------------------------------------------------------------

@app.get("/siga/contratos/{contratacao}", response_class=HTMLResponse)
def contrato(request: Request, contratacao: str, conn=Depends(conexao)):
    return _detalhe(request, "pages/contrato.html", D.contrato(conn, contratacao))


@app.get("/siga/contratos/{contratacao}/{secao}", response_class=HTMLResponse)
def contrato_secao(request: Request, contratacao: str, secao: str, pagina: str | None = None, conn=Depends(conexao)):
    if secao not in SECOES["contratos"]:
        return _nao_encontrado(request)
    dados = D.contrato_secao(conn, contratacao, secao, _pagina(pagina))
    return _detalhe(request, "pages/contrato.html", dados, secao)


@app.get("/siga/fornecedores/{cnpj_norm}", response_class=HTMLResponse)
def fornecedor(request: Request, cnpj_norm: str, conn=Depends(conexao)):
    dados = D.fornecedor(conn, cnpj_norm)
    # Chave antiga só com dígitos (CPF mascarado, documento zerado) → chave 'F…' atual.
    if not dados and _ID.fullmatch(cnpj_norm) and (nova := D.fornecedor_chave_antiga(conn, cnpj_norm)):
        return _302(f"/siga/fornecedores/{nova}")
    return _detalhe(request, "pages/fornecedor.html", dados)


@app.get("/siga/fornecedores/{cnpj_norm}/{secao}", response_class=HTMLResponse)
def fornecedor_secao(request: Request, cnpj_norm: str, secao: str, pagina: str | None = None, conn=Depends(conexao)):
    if secao not in SECOES["fornecedores"]:
        return _nao_encontrado(request)
    dados = D.fornecedor_secao(conn, cnpj_norm, secao, _pagina(pagina))
    return _detalhe(request, "pages/fornecedor.html", dados, secao)


@app.get("/siga/licitacoes/{id_licitacao}", response_class=HTMLResponse)
def licitacao(request: Request, id_licitacao: str, conn=Depends(conexao)):
    i = _int(id_licitacao)
    return _detalhe(request, "pages/licitacao.html", D.licitacao(conn, i) if i is not None else None)


@app.get("/siga/licitacoes/{id_licitacao}/{secao}", response_class=HTMLResponse)
def licitacao_secao(request: Request, id_licitacao: str, secao: str, pagina: str | None = None, conn=Depends(conexao)):
    i = _int(id_licitacao)
    if i is None or secao not in SECOES["licitacoes"]:
        return _nao_encontrado(request)
    dados = D.licitacao_secao(conn, i, secao, _pagina(pagina))
    return _detalhe(request, "pages/licitacao.html", dados, secao)


@app.get("/siga/atas/{id_ata}", response_class=HTMLResponse)
def ata(request: Request, id_ata: str, conn=Depends(conexao)):
    i = _int(id_ata)
    return _detalhe(request, "pages/ata.html", D.ata(conn, i) if i is not None else None)


@app.get("/siga/atas/{id_ata}/{secao}", response_class=HTMLResponse)
def ata_secao(request: Request, id_ata: str, secao: str, pagina: str | None = None, conn=Depends(conexao)):
    i = _int(id_ata)
    if i is None or secao not in SECOES["atas"]:
        return _nao_encontrado(request)
    dados = D.ata_secao(conn, i, secao, _pagina(pagina))
    return _detalhe(request, "pages/ata.html", dados, secao)


@app.get("/siga/compras/{id_processo}", response_class=HTMLResponse)
def compra(request: Request, id_processo: str, conn=Depends(conexao)):
    i = _int(id_processo)
    return _detalhe(request, "pages/compra.html", D.compra(conn, i) if i is not None else None)


@app.get("/siga/compras/{id_processo}/{secao}", response_class=HTMLResponse)
def compra_secao(request: Request, id_processo: str, secao: str, pagina: str | None = None, conn=Depends(conexao)):
    i = _int(id_processo)
    if i is None or secao not in SECOES["compras"]:
        return _nao_encontrado(request)
    dados = D.compra_secao(conn, i, secao, _pagina(pagina))
    return _detalhe(request, "pages/compra.html", dados, secao)


@app.get("/siga/itens/{id_item}", response_class=HTMLResponse)
def item(request: Request, id_item: str, origem: str | None = None, pagina: str | None = None, conn=Depends(conexao)):
    i = _int(id_item)
    dados = D.item(conn, i, origem=_p(origem), pagina=_pagina(pagina)) if i is not None else None
    return _detalhe(request, "pages/item.html", dados)


# ---------------------------------------------------------------------------
# Redirects legados (302: são de desenvolvimento)
# ---------------------------------------------------------------------------

_TIPO_LEGADO = {"contrato": "contratos", "fornecedor": "fornecedores", "licitacao": "licitacoes",
                "ata": "atas", "compra": "compras", "item": "itens"}


def _302(url: str):
    return RedirectResponse(url, status_code=302)


@app.get("/search")
def legado_search(q: str | None = None, tipo: str | None = None, ano: str | None = None, page: str | None = None):
    params: list[tuple[str, str]] = []
    if _p(q):
        params.append(("q", q.strip()))
    if tipo in _TIPO_LEGADO:
        params.append(("tipo", _TIPO_LEGADO[tipo]))
    if ano and _ANO.fullmatch(ano):
        params.append(("periodo", ano))
    if (n := _int(page)) and n > 1:
        params.append(("pagina", str(n)))
    return _302("/siga/busca" + ("?" + urlencode(params) if params else ""))


@app.get("/entity/contrato/{codigo}")
def legado_contrato(request: Request, codigo: str, conn=Depends(conexao)):
    r = conn.execute("SELECT contratacao FROM contratos WHERE codigo_contrato = ?", (codigo,)).fetchone()
    return _302(f"/siga/contratos/{r[0]}") if r else _nao_encontrado(request)


@app.get("/entity/fornecedor/{cnpj}")
def legado_fornecedor(cnpj: str):
    return _302(f"/siga/fornecedores/{cnpj}")


@app.get("/entity/licitacao/{id_}")
def legado_licitacao(id_: str):
    return _302(f"/siga/licitacoes/{id_}")


@app.get("/entity/ata/{id_}")
def legado_ata(id_: str):
    return _302(f"/siga/atas/{id_}")


@app.get("/entity/item/{id_}")
def legado_item(id_: str):
    return _302(f"/siga/itens/{id_}")


@app.get("/entity/compra/{src}/{src_id}")
def legado_compra(request: Request, src: str, src_id: str, conn=Depends(conexao)):
    r = None
    if src in ("compras_diretas", "outras_compras") and (i := _int(src_id)) is not None:
        r = conn.execute(f"SELECT id_processo FROM {src} WHERE rowid = ?", (i,)).fetchone()
    elif src == "ped" and (i := _int(src_id)) is not None:  # o ID PED é o próprio ID Processo da compra
        r = conn.execute("SELECT id_processo FROM compras_diretas WHERE id_processo = ? "
                         "UNION ALL SELECT id_processo FROM outras_compras WHERE id_processo = ? LIMIT 1",
                         (i, i)).fetchone()
    if not r or r[0] is None:
        return _nao_encontrado(request)
    return _302(f"/siga/compras/{r[0]}")
