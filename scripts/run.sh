#!/usr/bin/env bash
# Sobe o servidor de desenvolvimento.
set -euo pipefail
cd "$(dirname "$0")/.."
exec env PYTHONPATH=src .venv/bin/python -m uvicorn siga_search.app:app --host 127.0.0.1 --port 8765
