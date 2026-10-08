"""Conexão SQLite — read-only, com row factory dict-like."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "siga.db"


def get_conn() -> sqlite3.Connection:
    """Nova conexão read-only por request."""
    conn = sqlite3.connect(
        f"file:{DB_PATH}?mode=ro", uri=True, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -50000;")
    return conn


def conexao() -> Iterator[sqlite3.Connection]:
    """Dependência FastAPI: uma conexão por request, sempre fechada."""
    conn = get_conn()
    try:
        yield conn
    finally:
        conn.close()
