-- FTS5 — uma virtual table por entidade. Tokenizer unicode61 remove acentos.
-- Coluna `body` é o texto principal; `dt` (UNINDEXED) é a data canônica
-- usada para ordenar resultados em ordem decrescente (mais recente primeiro).
-- Formato de `dt`: ISO yyyy-mm-dd (ordenável lexicograficamente).

DROP TABLE IF EXISTS fts_item;
CREATE VIRTUAL TABLE fts_item USING fts5(
    body,
    id_item       UNINDEXED,
    cod_item      UNINDEXED,
    tipo          UNINDEXED,
    familia       UNINDEXED,
    classe        UNINDEXED,
    descricao     UNINDEXED,
    dt            UNINDEXED,  -- última atividade do item
    tokenize = "unicode61 remove_diacritics 2"
);

DROP TABLE IF EXISTS fts_fornecedor;
CREATE VIRTUAL TABLE fts_fornecedor USING fts5(
    body,
    cnpj_norm     UNINDEXED,
    cpf_cnpj      UNINDEXED,
    nome          UNINDEXED,
    cidade        UNINDEXED,
    uf            UNINDEXED,
    situacao      UNINDEXED,
    dt            UNINDEXED,  -- max(data_cadastro, último contrato)
    tokenize = "unicode61 remove_diacritics 2"
);

DROP TABLE IF EXISTS fts_licitacao;
CREATE VIRTUAL TABLE fts_licitacao USING fts5(
    body,
    id_licitacao  UNINDEXED,
    licitacao     UNINDEXED,
    unidade       UNINDEXED,
    objeto        UNINDEXED,
    modalidade    UNINDEXED,
    status        UNINDEXED,
    processo      UNINDEXED,
    dt            UNINDEXED,  -- coalesce(dt_homologacao, dt_publicacao)
    tokenize = "unicode61 remove_diacritics 2"
);

DROP TABLE IF EXISTS fts_ata;
CREATE VIRTUAL TABLE fts_ata USING fts5(
    body,
    id_ata        UNINDEXED,
    numero_ata    UNINDEXED,
    unidade       UNINDEXED,
    objeto        UNINDEXED,
    status        UNINDEXED,
    processo      UNINDEXED,  -- todos os processos da ata (ata_processos), separados por vírgula
    dt            UNINDEXED,  -- coalesce(fim_validade, inicio_validade)
    tokenize = "unicode61 remove_diacritics 2"
);

DROP TABLE IF EXISTS fts_contrato;
CREATE VIRTUAL TABLE fts_contrato USING fts5(
    body,
    codigo_contrato UNINDEXED,
    contratacao     UNINDEXED,
    unidade         UNINDEXED,
    objeto          UNINDEXED,
    fornecedor      UNINDEXED,
    cnpj_norm       UNINDEXED,
    status          UNINDEXED,
    processo        UNINDEXED,
    dt              UNINDEXED,  -- dt_contratacao
    tokenize = "unicode61 remove_diacritics 2"
);

DROP TABLE IF EXISTS fts_compra;
CREATE VIRTUAL TABLE fts_compra USING fts5(
    body,
    src           UNINDEXED,
    src_id        UNINDEXED,
    unidade       UNINDEXED,
    processo      UNINDEXED,
    objeto        UNINDEXED,
    fornecedor    UNINDEXED,
    cnpj_norm     UNINDEXED,
    valor         UNINDEXED,
    dt            UNINDEXED,  -- dt_aprovacao / inicio_disputa
    tokenize = "unicode61 remove_diacritics 2"
);
