# SIGA no Radar RJ

Módulo SIGA do Radar RJ: busca de contratos, fornecedores, licitações, atas, compras e itens do
Sistema Integrado de Gestão de Aquisições do Estado do Rio de Janeiro. Aparece como terceira fonte
de dados do Radar RJ, ao lado de Diário Oficial e SEI-RJ. Stack: Python + SQLite (FTS5) + FastAPI + Jinja2,
sem build de front-end.

## Como rodar

Requisitos: Python 3.11+, [uv](https://docs.astral.sh/uv/), `sqlite3` e `curl` na linha de comando.

```bash
# 1. (Uma vez) instalar dependências
uv venv --python 3.12
uv pip install -e .

# 2. Baixar a extração atual dos 21 CSVs para data/csv/
./scripts/baixar_csvs.sh

# 3. Construir o banco
./scripts/rebuild.sh    # monta data/siga.db.tmp e só então substitui data/siga.db

# 4. Subir o servidor
./scripts/run.sh        # http://127.0.0.1:8765/siga
```

`baixar_csvs.sh` baixa para `data/csv.baixando/` e só troca `data/csv/` se os 21 arquivos vierem
completos. Origem: `SIGA_CSV_URL` (padrão: Portal de Compras do RJ).

`rebuild.sh` lê os CSVs de `data/csv/` (ou de `SIGA_CSV_DIR`), carrega schema, ETL e FTS em
`data/siga.db.tmp`, confere que as tabelas principais não estão vazias e só então move o resultado
para `data/siga.db`. Se algo falhar, o banco atual fica intacto. O ETL lê as colunas pelo nome e
para com erro se faltar um CSV ou uma coluna obrigatória.

`RADAR_BASE_URL` (opcional) é a URL do Radar RJ usada nas pills Diário Oficial / SEI-RJ e nos links
da navegação. Padrão: `/`.

## Estrutura

```
.
├── src/siga_search/
│   ├── app.py            # rotas /siga, redirects das URLs antigas, 404
│   ├── search.py         # busca FTS, filtros, contagens, correspondência exata
│   ├── regras.py         # regras de negócio (situação derivada de contrato, ata, sanção)
│   ├── fmt.py            # filtros e globais Jinja (moeda, data, CNPJ, URLs de entidade)
│   ├── details/          # um módulo por entidade: get() e secao()
│   ├── db.py             # conexão read-only
│   ├── schema.sql, indexes.sql, fts.sql, etl.py, build_fts.py, normalize.py   # ETL do banco
├── scripts/
│   ├── baixar_csvs.sh    # baixa os CSVs para data/csv/
│   ├── rebuild.sh        # reconstrói data/siga.db a partir de data/csv/
│   └── run.sh            # servidor de desenvolvimento
├── templates/
│   ├── _base.html        # layout (faixa, rodapé)
│   ├── _ui.html          # macros de componentes
│   ├── _linhas.html      # linha de resultado por entidade
│   └── pages/            # home, busca, 404 e uma página por entidade
├── static/
│   ├── css/              # tokens.css, base.css, components.css e pages/<página>.css
│   ├── js/siga.js        # auto-envio de filtros e selects da home
│   └── img/              # wordmark Radar RJ e brasão do Governo do RJ
└── data/
    ├── csv/              # extração atual dos 21 CSVs (fora do git)
    └── siga.db           # banco SQLite gerado (fora do git)
```

## Rotas

| Rota | Descrição |
|---|---|
| `GET /siga` | Home (filtros + busca) |
| `GET /siga/busca?q=&tipo=&de=&ate=&orgao=&situacao=&ordem=&pagina=` | Resultados. `tipo`: `tudo`, `contratos`, `fornecedores`, `licitacoes`, `atas`, `compras`, `itens` |
| `GET /siga/contratos/{contratacao}` | Contrato. Seções: `itens`, `notas` |
| `GET /siga/fornecedores/{cnpj_norm}` | Fornecedor. Seções: `contratos`, `compras`, `licitacoes` |
| `GET /siga/licitacoes/{id_licitacao}` | Licitação. Seções: `participantes`, `itens`, `atas`, `contratos` |
| `GET /siga/atas/{id_ata}` | Ata de registro de preços. Seções: `itens`, `contratos`, `orgaos` |
| `GET /siga/compras/{id_processo}` | Compra (um registro por processo). Seções: `itens`, `contratos` |
| `GET /siga/itens/{id_item}?origem=&pagina=` | Item do catálogo e preços registrados |
| `GET /siga/<entidade>/<chave>/<secao>?pagina=` | Lista completa e paginada de uma seção |
| `GET /api/search?q=&tipo=` | Resultados em JSON |

As URLs antigas (`/`, `/search`, `/entity/...`) redirecionam para as novas. Fornecedor cuja chave antiga era só de dígitos (CPF mascarado) vai para a chave atual (`F…`) quando há exatamente uma; senão, 404.
