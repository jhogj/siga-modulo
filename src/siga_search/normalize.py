"""Normalizadores compartilhados pelo ETL."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime

_NON_DIGIT = re.compile(r"\D")
_WS = re.compile(r"\s+")
_INT = re.compile(r"[+-]?[0-9]+")
_NAO_ALNUM = re.compile(r"[^0-9a-z]+")


def s(v: str | None) -> str | None:
    """Strip + None se vazio."""
    if v is None:
        return None
    v = v.strip()
    return v if v else None


def cnpj_norm(v: str | None) -> str | None:
    """Remove tudo que não é dígito; retorna None somente se ficar vazio."""
    if v is None:
        return None
    digits = _NON_DIGIT.sub("", v)
    if not digits:
        return None
    return digits


def eh_cnpj(digits: str) -> bool:
    """14 dígitos e diferente de zeros."""
    return len(digits) == 14 and digits != "00000000000000"


def chave_fornecedor(doc: str | None, id_forn: int | None) -> str | None:
    """Chave do fornecedor: dígitos do CNPJ; senão 'F' + ID Forn; sem ID Forn, os dígitos."""
    digits = _NON_DIGIT.sub("", doc or "")
    if eh_cnpj(digits):
        return digits
    if id_forn is not None:
        return f"F{id_forn}"
    return digits or None


def sem_acento(v: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", v) if not unicodedata.combining(c))


def nome_norm(v: str | None) -> str:
    """Nome para comparação: sem acento, minúsculo, só letras/dígitos separados por espaço."""
    return _NAO_ALNUM.sub(" ", sem_acento(v or "").casefold()).strip()


def processo_norm(v: str | None) -> str | None:
    """Uppercase + colapsa espaços. Mantém pontuação (E-XX/..., SEI-...)."""
    if v is None:
        return None
    v = _WS.sub("", v).upper()
    return v or None


def parse_int(v: str | None) -> int | None:
    """Inteiro estrito: qualquer outro texto vira None (não extrai dígitos)."""
    if v is None:
        return None
    v = v.strip()
    if not _INT.fullmatch(v):
        return None
    return int(v)


def parse_decimal(v: str | None) -> float | None:
    """Aceita formato BR (1.234,56) ou puro (1234.56). Retorna None se inválido."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if "," in v:
        # Brasileiro: '.' é separador de milhar, ',' é decimal
        v = v.replace(".", "").replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def parse_date(v: str | None) -> str | None:
    """dd/mm/yyyy ou dd/mm/yyyy HH:MM:SS → ISO. None em datas inválidas."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    has_time = " " in v
    fmt = "%d/%m/%Y %H:%M:%S" if has_time else "%d/%m/%Y"
    try:
        dt = datetime.strptime(v, fmt)
    except ValueError:
        return None
    # Sanity check: 1900..2100
    if dt.year < 1900 or dt.year > 2100:
        return None
    if has_time:
        return dt.isoformat(timespec="seconds")
    return dt.date().isoformat()
