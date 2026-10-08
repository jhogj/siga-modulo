"""Filtros, testes e globais Jinja e URLs de entidade.

Todo filtro tolera None, "" e "None" e devolve "" nesses casos (exceto quando indicado).
"""
from __future__ import annotations

import os
import re
from datetime import date
from urllib.parse import urlencode

from jinja2 import Undefined
from markupsafe import Markup

from . import regras
from .details._comum import MOSTRAR_TUDO_ATE, POR_PAGINA, PREVIA, corte

RADAR_URL = os.environ.get("RADAR_BASE_URL", "/") or "/"
EXTRACAO = ""  # preenchido por app.py no startup (SELECT data_extracao FROM contratos LIMIT 1)

_VAZIOS = {"", "none", "null", "nan"}


def _vazio(v) -> bool:
    if v is None or isinstance(v, Undefined):
        return True
    if isinstance(v, float) and v != v:  # NaN
        return True
    if isinstance(v, str):
        if isinstance(v, Markup):
            return v.striptags().strip().lower() in _VAZIOS and "<img" not in v
        return v.strip().lower() in _VAZIOS
    return False


def presente(v) -> bool:
    """Teste Jinja `presente`: falso para None, "", espaços, "None", "null", "nan" e Markup vazio."""
    return not _vazio(v)


def _num(v) -> float | None:
    if _vazio(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _milhar(inteiro: str) -> str:
    neg = inteiro.startswith("-")
    s = inteiro.lstrip("-")
    grupos = []
    while len(s) > 3:
        grupos.insert(0, s[-3:])
        s = s[:-3]
    grupos.insert(0, s)
    return ("-" if neg else "") + ".".join(grupos)


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def moeda(v) -> str:
    n = _num(v)
    if n is None:
        return ""
    s = f"{abs(n):.2f}"
    inteiro, dec = s.split(".")
    return f"{'-' if n < 0 else ''}R$ {_milhar(inteiro)},{dec}"


def data(v) -> str:
    if _vazio(v):
        return ""
    s = str(v).strip()
    m = re.fullmatch(r"([0-9]{2})/([0-9]{2})/([0-9]{4})", s)
    if m:
        d, mes, a = m.group(1), m.group(2), m.group(3)
    else:
        m = re.match(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", s)
        if not m:
            return ""
        a, mes, d = m.group(1), m.group(2), m.group(3)
    try:  # data impossível (2022-02-30) some, como as vazias
        date(int(a), int(mes), int(d))
    except ValueError:
        return ""
    return f"{d}/{mes}/{a}"


def datahora(v) -> str:
    if _vazio(v):
        return ""
    s = str(v).strip()
    d = data(s)
    m = re.match(r"\d{4}-\d{2}-\d{2}[T ](\d{2}):(\d{2})", s)
    return f"{d}, {m.group(1)}:{m.group(2)}" if (d and m) else d


def num(v) -> str:
    n = _num(v)
    if n is None:
        return ""
    if n != int(n):
        return qtd(n)
    return _milhar(str(int(n)))


def qtd(v) -> str:
    n = _num(v)
    if n is None:
        return ""
    s = f"{abs(n):.3f}".rstrip("0").rstrip(".")
    inteiro, _, dec = s.partition(".")
    out = _milhar(inteiro) + ("," + dec if dec else "")
    return ("-" if n < 0 and out != "0" else "") + out


def pct(v) -> str:
    n = _num(v)
    if n is None:
        return ""
    s = f"{n:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + "%"


def doc(v) -> str:
    if _vazio(v):
        return ""
    s = str(v).strip()
    if re.fullmatch(r"\d{14}", s):
        return f"{s[:2]}.{s[2:5]}.{s[5:8]}/{s[8:12]}-{s[12:]}"
    if re.fullmatch(r"\d{11}", s):
        return f"{s[:3]}.{s[3:6]}.{s[6:9]}-{s[9:]}"
    return s


def doc_rotulo(v) -> str:
    """CNPJ (14 dígitos), CPF (mascarado ou 11 dígitos); documento irregular: rótulo neutro."""
    if _vazio(v):
        return ""
    v = str(v)
    digitos = len(re.sub(r"\D", "", v))
    if "*" in v or digitos == 11:
        return "CPF"
    return "CNPJ" if digitos == 14 else "Documento"


def processo(v) -> str:
    if _vazio(v):
        return ""
    return str(v).strip().lstrip("*").strip()


def limpo(v) -> str:
    if _vazio(v):
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def sigla(v) -> str:
    if _vazio(v):
        return ""
    s = str(v).strip()
    return s.split(" - ", 1)[0].strip() if " - " in s else s


def modalidade(v) -> str:
    if _vazio(v):
        return ""
    return re.sub(r"\s+-\s+(Lei\s+)?[\d./]+$", "", str(v).strip())


def natureza_juridica(v) -> str:
    if _vazio(v):
        return ""
    return re.sub(r"\s*\([^()]*\)\s*$", "", str(v).strip())


def penalidade(v) -> str:
    if _vazio(v):
        return ""
    achados = re.findall(r"\(([^()]*)\)", str(v))
    return achados[-1].strip() if achados else ""


ELEMENTOS_DESPESA = {
    "04": "Contratação por tempo determinado",
    "08": "Outros benefícios assistenciais",
    "14": "Diárias – civil",
    "27": "Encargos pela honra de avais, garantias, seguros e similares",
    "30": "Material de consumo",
    "31": "Premiações culturais, artísticas, científicas, desportivas e outras",
    "32": "Material, bem ou serviço para distribuição gratuita",
    "33": "Passagens e despesas com locomoção",
    "34": "Outras despesas de pessoal decorrentes de contratos de terceirização",
    "35": "Serviços de consultoria",
    "36": "Outros serviços de terceiros – pessoa física",
    "37": "Locação de mão de obra",
    "39": "Outros serviços de terceiros – pessoa jurídica",
    "40": "Serviços de tecnologia da informação e comunicação – pessoa jurídica",
    "41": "Contribuições",
    "43": "Subvenções sociais",
    "46": "Auxílio-alimentação",
    "47": "Obrigações tributárias e contributivas",
    "51": "Obras e instalações",
    "52": "Equipamentos e material permanente",
    "61": "Aquisição de imóveis",
    "91": "Sentenças judiciais",
    "92": "Despesas de exercícios anteriores",
    "93": "Indenizações e restituições",
}


def natureza_despesa(v) -> str:
    if _vazio(v):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    nome = ELEMENTOS_DESPESA.get(s[-2:]) if len(s) >= 2 else None
    return f"{s} – {nome}" if nome else s


_UNIDADES = {"UN": "un.", "KG": "kg", "CX": "cx.", "PCT": "pct.", "SERVICO": "serviço", "L": "L",
             "MENSAL": "mensal", "ANUAL": "anual", "VAGA": "vaga", "FR": "fr.", "M": "m", "M2": "m²",
             "M3": "m³", "MES": "mês", "DIARIA": "diária", "PAR": "par", "TESTE": "teste", "ANO": "ano",
             "PARTICIPANTE": "participante", "BLOCO": "bloco", "KIT": "kit", "POSTO": "posto",
             "LOCACAO": "locação", "PUBLICACAO": "publicação", "DOCUMENTO": "documento", "ANUIDADE": "anuidade"}
# Unidades por extenso flexionam com a quantidade ("6 serviços", "12 meses"); abreviações e adjetivos
# (un., kg, mensal, anual) ficam invariáveis.
_UNIDADES_PLURAL = {"serviço": "serviços", "vaga": "vagas", "mês": "meses", "diária": "diárias", "par": "pares",
                    "teste": "testes", "ano": "anos", "participante": "participantes", "bloco": "blocos",
                    "kit": "kits", "posto": "postos", "locação": "locações", "publicação": "publicações",
                    "documento": "documentos", "anuidade": "anuidades"}


def unidade_medida(v, quantidade=None) -> str:
    """`un|unidade_medida` dá a forma singular; `un|unidade_medida(qtd)` flexiona pela quantidade (≥ 2 → plural)."""
    if _vazio(v):
        return ""
    s = str(v).strip()
    u = _UNIDADES.get(s.upper(), s.lower())
    q = _num(quantidade)
    return _UNIDADES_PLURAL.get(u, u) if q is not None and abs(q) >= 2 else u


def qtd_unidade(quantidade, un=None) -> str:
    """`r.qtd|qtd_unidade(r.un)` → "6 serviços", "12 meses", "60 kg"; sem unidade, só a quantidade."""
    q = qtd(quantidade)
    if not q:
        return ""
    return f"{q} {unidade_medida(un, quantidade)}".strip()


def tipo_item(v) -> str:
    if _vazio(v):
        return ""
    s = str(v).strip().upper()
    return {"MATERIAL": "Material", "SERVICOS": "Serviço", "SERVICO": "Serviço"}.get(s, str(v).strip())


def item_numero(v) -> str:
    if _vazio(v):
        return ""
    m = re.search(r"Item:\s*(\d+)", str(v))
    return m.group(1) if m else str(v).strip()


def slug(v) -> str:
    """Âncora/ID estável a partir de um título ("Itens contratados" → "itens-contratados")."""
    if _vazio(v):
        return ""
    import unicodedata
    s = unicodedata.normalize("NFKD", str(v)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# ---------------------------------------------------------------------------
# Globais
# ---------------------------------------------------------------------------

def hoje() -> str:
    return date.today().isoformat()


def local(cidade, uf) -> str:
    c = limpo(cidade)
    u = limpo(uf)
    if not c:
        return ""
    if re.search(r"\s-\s[A-Z]{2}$", c):
        return c
    if u and u.upper() != "OU":
        return f"{c} - {u}"
    return c


def plural(n, singular: str, plural_: str) -> str:
    v = _num(n) or 0
    return f"{num(v)} {singular if v == 1 else plural_}"


def url_with(request, **params) -> str:
    """Caminho atual + query com `params` substituídos; None ou "" remove a chave."""
    pares = list(request.query_params.multi_items())
    chaves = [k for k, _ in pares]
    saida: list[tuple[str, str]] = []
    vistos = set()
    for k, v in pares:
        if k in params:
            if k in vistos:
                continue
            vistos.add(k)
            nv = params[k]
            if nv is None or nv == "":
                continue
            saida.append((k, str(nv)))
        else:
            saida.append((k, v))
    for k, nv in params.items():
        if k not in chaves and nv is not None and nv != "":
            saida.append((k, str(nv)))
    qs = urlencode(saida)
    return request.url.path + (f"?{qs}" if qs else "")


def _url(prefixo: str, chave) -> str:
    if _vazio(chave):
        return ""
    return f"/siga/{prefixo}/{chave}"


def url_contrato(contratacao) -> str:
    return _url("contratos", contratacao)


def url_fornecedor(cnpj_norm) -> str:
    return _url("fornecedores", cnpj_norm)


def url_licitacao(id_licitacao) -> str:
    return _url("licitacoes", id_licitacao)


def url_ata(id_ata) -> str:
    return _url("atas", id_ata)


def url_compra(id_processo) -> str:
    return _url("compras", id_processo)


def url_item(id_item) -> str:
    return _url("itens", id_item)


FILTROS = {f.__name__: f for f in (
    moeda, data, datahora, num, qtd, pct, doc, doc_rotulo, processo, limpo, sigla, modalidade,
    natureza_juridica, penalidade, natureza_despesa, unidade_medida, qtd_unidade, tipo_item, item_numero, slug,
)}

def opcoes(itens, orgao: bool = False) -> list[dict]:
    """Opções de `ui.menu`: valores, pares (valor, texto) ou trios (valor, texto, contagem).

    Com `orgao=True`, o texto "FES - FUNDO ESTADUAL DE SAÚDE" vira sigla ("FES") + nome.
    """
    saida = []
    for it in itens or []:
        if isinstance(it, str):
            v, t, n = it, it, None
        else:
            v, t = it[0], it[1] if len(it) > 1 else it[0]
            n = it[2] if len(it) > 2 else None
            if orgao and len(it) == 2 and isinstance(it[1], int):  # (unidade, contagem)
                t, n = v, it[1]
        s = None
        if orgao and " - " in str(t):
            s, t = (x.strip() for x in str(t).split(" - ", 1))
        saida.append({"v": v, "t": t, "s": s, "n": n})
    return saida


GLOBAIS = {
    "hoje": hoje, "local": local, "plural": plural, "url_with": url_with, "opcoes": opcoes,
    "url_contrato": url_contrato, "url_fornecedor": url_fornecedor, "url_licitacao": url_licitacao,
    "url_ata": url_ata, "url_compra": url_compra, "url_item": url_item,
    "situacao_contrato": regras.situacao_contrato, "situacao_ata": regras.situacao_ata,
    "situacao_sancao": regras.situacao_sancao, "alerta_licitacao": regras.alerta_licitacao,
    "alerta_fornecedor": regras.alerta_fornecedor, "alerta_item": regras.alerta_item,
    "MOSTRAR_TUDO_ATE": MOSTRAR_TUDO_ATE, "PREVIA": PREVIA, "POR_PAGINA": POR_PAGINA, "corte": corte,
}


def registrar(env, extracao: str | None = None) -> None:
    """Registra filtros, o teste `presente` e os globais no ambiente Jinja."""
    env.filters.update(FILTROS)
    env.tests["presente"] = presente
    env.globals.update(GLOBAIS)
    env.globals["RADAR_URL"] = RADAR_URL
    env.globals["EXTRACAO"] = extracao if extracao is not None else EXTRACAO
