#!/usr/bin/env bash
# Recria o banco a partir dos CSVs (padrão data/csv; outro diretório via SIGA_CSV_DIR).
# Monta em data/siga.db.tmp e só substitui data/siga.db quando o novo estiver pronto.
set -euo pipefail
cd "$(dirname "$0")/.."

CSV_DIR="${SIGA_CSV_DIR:-data/csv}"
TMP="data/siga.db.tmp"
PY=(env PYTHONPATH=src .venv/bin/python)

rm -f "$TMP" "$TMP-shm" "$TMP-wal" "$TMP-journal"
sqlite3 "$TMP" < src/siga_search/schema.sql
"${PY[@]}" -m siga_search.etl --db "$TMP" --csv-dir "$CSV_DIR"
"${PY[@]}" -m siga_search.build_fts --db "$TMP"

# Confere tabelas-chave e deixa o banco num arquivo só (sem -wal) antes de mover.
"${PY[@]}" - "$TMP" <<'EOF'
import sqlite3
import sys

TABELAS = [
    "catalogo", "fornecedores", "licitacoes", "atas_registro_preco", "ata_processos",
    "contratos", "compras_diretas", "outras_compras", "itens_licitacoes",
    "itens_atas_registro_preco", "itens_contratos", "participantes",
    "fts_item", "fts_fornecedor", "fts_licitacao", "fts_ata", "fts_contrato", "fts_compra",
]
conn = sqlite3.connect(sys.argv[1])
vazias = [t for t in TABELAS if conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] == 0]
if vazias:
    sys.exit(f"erro: tabelas vazias: {', '.join(vazias)}; data/siga.db não foi alterado")
conn.execute("PRAGMA journal_mode = DELETE")
conn.close()
EOF

rm -f data/siga.db-shm data/siga.db-wal
mv "$TMP" data/siga.db
echo "Pronto: data/siga.db"
