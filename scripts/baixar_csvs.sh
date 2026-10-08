#!/usr/bin/env bash
# Baixa a extração atual dos 21 CSVs do SIGA para data/csv/ (origem usada pelo ETL).
# Baixa para um diretório temporário e só substitui data/csv/ se todos os arquivos vierem.
set -euo pipefail
cd "$(dirname "$0")/.."

BASE="${SIGA_CSV_URL:-https://www.compras.rj.gov.br/siga/imagens}"
ARQUIVOS=(
  ACOMPANHAMENTO_ASSAPC ATA_REGISTRO_PRECO CATALOGO COMPRAS_DIRETAS CONTRATOS FORNECEDORES
  FORNECEDOR_HISTORICO_CONTRATACOES FORNECEDOR_MAPEAMENTOS FORNECEDOR_SANCOES HISTORICO_PRECOS_ATAS
  HISTORICO_PRECOS_CD HISTORICO_PRECOS_LICIT ITENS_ATAS_REGISTRO_PRECO ITENS_CONTRATOS ITENS_LICITACOES
  LICITACOES OUTRAS_COMPRAS PARTICIPANTES PARTICIPANTES_ATAS_REGISTRO_PRECO PROCESSOS_ELETRONICOS_DISPENSA
  SANCOES
)

TMP="data/csv.baixando"
rm -rf "$TMP"
mkdir -p "$TMP"
for a in "${ARQUIVOS[@]}"; do
  echo "baixando $a.CSV"
  curl -fsS --retry 3 --retry-delay 5 -o "$TMP/$a.CSV" "$BASE/$a.CSV"
  if [ ! -s "$TMP/$a.CSV" ]; then
    echo "erro: $a.CSV veio vazio" >&2
    exit 1
  fi
done

rm -rf data/csv
mv "$TMP" data/csv
echo "Pronto: data/csv ($(ls data/csv | wc -l | tr -d ' ') arquivos)"
