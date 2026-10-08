-- SIGA — Schema relacional SQLite (somente CREATE TABLE).
-- Índices em indexes.sql, criados após ingestão.

-- ============================================================
-- DIMENSÕES
-- ============================================================

-- Catálogo: hierarquia Tipo > Família > Classe > Artigo > Item
CREATE TABLE IF NOT EXISTS catalogo (
    id_item        INTEGER PRIMARY KEY,
    id_tipo        INTEGER,
    tipo           TEXT,
    id_familia     INTEGER,
    familia        TEXT,
    id_classe      INTEGER,
    classe         TEXT,
    id_artigo      TEXT,
    artigo         TEXT,
    cod_item       TEXT,
    descricao      TEXT,
    sustentavel    TEXT,
    data_extracao  TEXT
);

-- Fornecedores. cnpj_norm é a chave: dígitos do CNPJ (14 dígitos, não zerado);
-- senão 'F' + ID Forn (CPF mascarado, documento estrangeiro ou inválido).
-- Nas outras tabelas: CNPJ da linha; sem CNPJ, a chave que o ID Forn tem aqui
-- (exceto participantes: linha sem CNPJ fica sem chave).
-- CNPJ com mais de um ID Forn fica com a 1ª linha. Exibir sempre cpf_cnpj, nunca a chave.
CREATE TABLE IF NOT EXISTS fornecedores (
    cnpj_norm        TEXT PRIMARY KEY,
    id_forn          INTEGER,
    cpf_cnpj         TEXT,
    nome             TEXT,
    crc              TEXT,
    tipo_empresarial TEXT,
    me_epp           TEXT,
    situacao         TEXT,
    data_cadastro    TEXT,
    cidade           TEXT,
    uf               TEXT,
    data_extracao    TEXT
);

-- Licitações
CREATE TABLE IF NOT EXISTS licitacoes (
    id_licitacao             INTEGER PRIMARY KEY,
    licitacao                TEXT,
    unidade                  TEXT,
    objeto                   TEXT,
    modalidade               TEXT,
    criterio_julgamento      TEXT,
    srp                      TEXT,
    dt_publicacao            TEXT,
    dt_limite_proposta       TEXT,
    dt_abertura              TEXT,
    dt_homologacao           TEXT,
    dt_adjudicacao           TEXT,
    status                   TEXT,
    valor_total_homologado   REAL,
    valor_total_estimado     REAL,
    internacional            TEXT,
    processo                 TEXT,
    processo_norm            TEXT,
    regime                   TEXT,
    data_extracao            TEXT
);

-- Atas de Registro de Preço.
-- Dimensão deduplicada por ID Ata.
-- `id_processo`/`processo` guardam só o 1º processo da ata; todos estão em ata_processos.
-- O campo `id_processo`/`processo` não deve ser usado como FK direta para contratos.
CREATE TABLE IF NOT EXISTS atas_registro_preco (
    id_ata               INTEGER PRIMARY KEY,
    numero_ata           TEXT,
    unidade_gerenciadora TEXT,
    objeto               TEXT,
    licitacao_sigla      TEXT,
    inicio_validade      TEXT,
    fim_validade         TEXT,
    criterio_julgamento  TEXT,
    cont_tempo_servico   TEXT,
    status_ata           TEXT,
    id_licitacao         INTEGER,
    id_processo          INTEGER,
    processo             TEXT,
    processo_norm        TEXT,
    data_extracao        TEXT,
    FOREIGN KEY (id_licitacao) REFERENCES licitacoes(id_licitacao)
);

-- Todos os processos de cada ata (ATA_REGISTRO_PRECO traz uma linha por processo).
CREATE TABLE IF NOT EXISTS ata_processos (
    id_ata         INTEGER NOT NULL,
    id_processo    INTEGER,
    processo       TEXT,
    processo_norm  TEXT,
    PRIMARY KEY (id_ata, processo_norm),
    FOREIGN KEY (id_ata) REFERENCES atas_registro_preco(id_ata)
);

-- Contratos. `codigo_contrato` e `contratacao` são chaves únicas nos dados.
CREATE TABLE IF NOT EXISTS contratos (
    codigo_contrato        TEXT PRIMARY KEY,
    id_processo            INTEGER,
    id_licitacao           INTEGER,
    contratacao            TEXT,
    status_contratacao     TEXT,
    dt_contratacao         TEXT,
    unidade                TEXT,
    processo               TEXT,
    processo_norm          TEXT,
    objeto                 TEXT,
    tipo_aquisicao         TEXT,
    criterio_julgamento    TEXT,
    dt_inicio_vigencia     TEXT,
    dt_fim_vigencia        TEXT,
    fornecedor             TEXT,
    cpf_cnpj               TEXT,
    cnpj_norm              TEXT,
    id_forn                INTEGER,
    valor_total_contrato   REAL,
    valor_total_empenhado  REAL,
    valor_total_liquidado  REAL,
    valor_total_pago       REAL,
    dt_public_deorj        TEXT,
    regime_juridico        TEXT,
    url_pncp               TEXT,
    data_extracao          TEXT,
    UNIQUE (contratacao),
    FOREIGN KEY (id_licitacao) REFERENCES licitacoes(id_licitacao),
    FOREIGN KEY (cnpj_norm)    REFERENCES fornecedores(cnpj_norm)
);

-- Compras Diretas. A disputa eletrônica da compra é ped.id_ped = compras_diretas.id_processo.
-- O campo textual `ped` não é chave relacional.
CREATE TABLE IF NOT EXISTS compras_diretas (
    id_processo         INTEGER,
    unidade             TEXT,
    processo            TEXT,
    processo_norm       TEXT,
    objeto              TEXT,
    afastamento         TEXT,
    enquadramento_legal TEXT,
    dt_aprovacao        TEXT,
    valor_processo      REAL,
    cpf_cnpj            TEXT,
    cnpj_norm           TEXT,
    id_forn             INTEGER,
    fornecedor_vencedor TEXT,
    id_item             INTEGER,
    item                TEXT,
    qtd                 REAL,
    unidade_medida      TEXT,
    vl_unitario         REAL,
    ped                 TEXT,
    regime              TEXT,
    temporalidade       TEXT,
    data_extracao       TEXT,
    FOREIGN KEY (cnpj_norm) REFERENCES fornecedores(cnpj_norm),
    FOREIGN KEY (id_item)   REFERENCES catalogo(id_item)
);

-- Outras Compras (adesões, renovações)
CREATE TABLE IF NOT EXISTS outras_compras (
    id_processo         INTEGER,
    unidade             TEXT,
    processo            TEXT,
    processo_norm       TEXT,
    objeto              TEXT,
    afastamento         TEXT,
    enquadramento_legal TEXT,
    dt_aprovacao        TEXT,
    valor_processo      REAL,
    cpf_cnpj            TEXT,
    cnpj_norm           TEXT,
    id_forn             INTEGER,
    fornecedor_vencedor TEXT,
    id_item             INTEGER,
    item                TEXT,
    qtd                 REAL,
    unidade_medida      TEXT,
    vl_unitario         REAL,
    regime              TEXT,
    data_extracao       TEXT,
    FOREIGN KEY (cnpj_norm) REFERENCES fornecedores(cnpj_norm),
    FOREIGN KEY (id_item)   REFERENCES catalogo(id_item)
);

-- Processos Eletrônicos de Dispensa (PED).
-- id_ped NÃO é único: cada linha é um item da disputa. id_ped é o ID Processo da compra
-- (compras_diretas.id_processo ou outras_compras.id_processo); nunca usar COMPRAS_DIRETAS.PED.
-- cnpj_norm vem do ID Forn via fornecedores (NULL se não houver).
CREATE TABLE IF NOT EXISTS ped (
    id_ped              INTEGER,
    processo            TEXT,
    processo_norm       TEXT,
    ano_ped             INTEGER,
    status_ped          TEXT,
    unidade             TEXT,
    nu_pesquisa         TEXT,
    objeto              TEXT,
    inicio_disputa      TEXT,
    fim_disputa         TEXT,
    id_item             INTEGER,
    item                TEXT,
    qtd                 REAL,
    status_item         TEXT,
    justificativa       TEXT,
    fornecedor_vencedor TEXT,
    id_forn             INTEGER,
    cnpj_norm           TEXT,
    lances              TEXT,
    outras_propostas    TEXT,
    data_extracao       TEXT,
    FOREIGN KEY (id_item)   REFERENCES catalogo(id_item),
    FOREIGN KEY (cnpj_norm) REFERENCES fornecedores(cnpj_norm)
);

-- ============================================================
-- FATOS / TABELAS DE LIGAÇÃO
-- ============================================================

CREATE TABLE IF NOT EXISTS itens_licitacoes (
    id_licitacao            INTEGER,
    licitacao               TEXT,
    unidade                 TEXT,
    modalidade              TEXT,
    itens_lotes             TEXT,
    id_item                 INTEGER,
    familia                 TEXT,
    classe                  TEXT,
    artigo                  TEXT,
    descricao               TEXT,
    quantidade              REAL,
    valor_total_homologado  REAL,
    taxa_homologada         REAL,
    exclusivo_me_epp        TEXT,
    situacao_item           TEXT,
    dt_homologacao_licit    TEXT,
    data_extracao           TEXT,
    FOREIGN KEY (id_licitacao) REFERENCES licitacoes(id_licitacao),
    FOREIGN KEY (id_item)      REFERENCES catalogo(id_item)
);

-- Itens e participantes de ata: a extração repete cada linha pelo nº de processos da ata;
-- a carga divide essa repetição (linhas iguais legítimas ficam). cnpj_norm vem do ID Forn via fornecedores.
CREATE TABLE IF NOT EXISTS itens_atas_registro_preco (
    id_ata              INTEGER,
    numero_ata          TEXT,
    criterio_julgamento TEXT,
    id_item             INTEGER,
    item                TEXT,
    fornecedor          TEXT,
    id_forn             INTEGER,
    cnpj_norm           TEXT,
    qtd                 REAL,
    vl_unitario         REAL,
    taxa_pct            REAL,
    data_extracao       TEXT,
    FOREIGN KEY (id_ata)    REFERENCES atas_registro_preco(id_ata),
    FOREIGN KEY (id_item)   REFERENCES catalogo(id_item),
    FOREIGN KEY (cnpj_norm) REFERENCES fornecedores(cnpj_norm)
);

CREATE TABLE IF NOT EXISTS participantes_atas_registro_preco (
    id_ata               INTEGER,
    numero_ata           TEXT,
    unidade_participante TEXT,
    criterio_julgamento  TEXT,
    item                 TEXT,
    id_item              INTEGER,
    qtd_demandada        REAL,
    qtd_consumida        REAL,
    valor_demandado      REAL,
    valor_consumido      REAL,
    data_extracao        TEXT,
    FOREIGN KEY (id_ata)  REFERENCES atas_registro_preco(id_ata),
    FOREIGN KEY (id_item) REFERENCES catalogo(id_item)
);

CREATE TABLE IF NOT EXISTS itens_contratos (
    contratacao                  TEXT,
    id_ata                       INTEGER,
    id_item                      INTEGER,
    item                         TEXT,
    qtd_original                 REAL,
    vl_unit_original             REAL,
    total_aditivada_suprimida    REAL,
    vl_unit_aditivado_suprimido  REAL,
    elemento                     TEXT,
    subelemento                  TEXT,
    data_extracao                TEXT,
    FOREIGN KEY (contratacao) REFERENCES contratos(contratacao),
    FOREIGN KEY (id_item) REFERENCES catalogo(id_item),
    FOREIGN KEY (id_ata)  REFERENCES atas_registro_preco(id_ata)
);

-- Participantes (lances) por item de licitação
CREATE TABLE IF NOT EXISTS participantes (
    id_lic                INTEGER,
    nu_lic                TEXT,
    sigla                 TEXT,
    unidade               TEXT,
    modalidade            TEXT,
    exclusivo_mpe         TEXT,
    id_familia            INTEGER,
    familia               TEXT,
    id_classe             INTEGER,
    classe                TEXT,
    id_artigo             TEXT,
    artigo                TEXT,
    id_item               INTEGER,
    itens_lotes           TEXT,
    descricao             TEXT,
    quantidade            REAL,
    situacao_item         TEXT,
    fornecedor            TEXT,
    data_cadastro         TEXT,
    mpe                   TEXT,
    cpf_cnpj              TEXT,
    cnpj_norm             TEXT,
    id_forn               INTEGER,
    fornecedor_vencedor   TEXT,
    valor_unit_ofertado   REAL,
    taxa_ofertada         REAL,
    data_extracao         TEXT,
    FOREIGN KEY (id_lic)    REFERENCES licitacoes(id_licitacao),
    FOREIGN KEY (id_item)   REFERENCES catalogo(id_item),
    FOREIGN KEY (cnpj_norm) REFERENCES fornecedores(cnpj_norm)
);

-- Mapeamento fornecedor × Família/Classe (4M linhas).
-- Sem ID Forn no CSV: CNPJ => dígitos; documento mascarado => fornecedor com o mesmo
-- documento e nome, se houver exatamente um (senão cnpj_norm NULL). Idem no histórico abaixo.
CREATE TABLE IF NOT EXISTS fornecedor_mapeamentos (
    cpf_cnpj       TEXT,
    cnpj_norm      TEXT,
    nome           TEXT,
    familia        TEXT,
    classe         TEXT,
    data_extracao  TEXT,
    FOREIGN KEY (cnpj_norm) REFERENCES fornecedores(cnpj_norm)
);

-- Histórico de contratações por fornecedor
CREATE TABLE IF NOT EXISTS fornecedor_historico_contratacoes (
    nome                     TEXT,
    cpf_cnpj                 TEXT,
    cnpj_norm                TEXT,
    contratacao              TEXT,
    dt_contratacao           TEXT,
    processo                 TEXT,
    processo_norm            TEXT,
    unidade                  TEXT,
    valor_total_contratado   REAL,
    valor_total_executado    REAL,
    tipo_aquisicao           TEXT,
    data_extracao            TEXT,
    FOREIGN KEY (cnpj_norm)   REFERENCES fornecedores(cnpj_norm),
    FOREIGN KEY (contratacao) REFERENCES contratos(contratacao)
);

-- Históricos de preços (3 fontes)
CREATE TABLE IF NOT EXISTS historico_precos_atas (
    tipo            TEXT,
    familia         TEXT,
    classe          TEXT,
    artigo          TEXT,
    id_item         INTEGER,
    descricao       TEXT,
    ata_srp         TEXT,
    licitacao       TEXT,
    unidade_gestora TEXT,
    fornecedor      TEXT,
    validade_ata    TEXT,
    qtd             REAL,
    vl_unitario     REAL,
    data_extracao   TEXT,
    FOREIGN KEY (id_item) REFERENCES catalogo(id_item)
);

CREATE TABLE IF NOT EXISTS historico_precos_cd (
    tipo              TEXT,
    familia           TEXT,
    classe            TEXT,
    artigo            TEXT,
    id_item           INTEGER,
    descricao         TEXT,
    id_processo       INTEGER,
    processo          TEXT,
    processo_norm     TEXT,
    tipo_compra       TEXT,
    unidade_compradora TEXT,
    fornecedor        TEXT,
    dt_aprovacao      TEXT,
    qtd               REAL,
    vl_unitario       REAL,
    contratacao       TEXT,
    data_extracao     TEXT,
    FOREIGN KEY (id_item)     REFERENCES catalogo(id_item),
    FOREIGN KEY (contratacao) REFERENCES contratos(contratacao)
);

CREATE TABLE IF NOT EXISTS historico_precos_licit (
    tipo              TEXT,
    familia           TEXT,
    classe            TEXT,
    artigo            TEXT,
    id_item           INTEGER,
    descricao         TEXT,
    licitacao         TEXT,
    modalidade_compra TEXT,
    unidade_compradora TEXT,
    fornecedor        TEXT,
    dt_homologacao    TEXT,
    qtd               REAL,
    vl_unitario       REAL,
    contratacao       TEXT,
    data_extracao     TEXT,
    FOREIGN KEY (id_item)     REFERENCES catalogo(id_item),
    FOREIGN KEY (contratacao) REFERENCES contratos(contratacao)
);

-- Acompanhamento ASSAPC (empenho/orçamento)
CREATE TABLE IF NOT EXISTS acompanhamento_assapc (
    unidade                   TEXT,
    processo                  TEXT,
    processo_norm             TEXT,
    dt_criacao_processo       TEXT,
    status_processo           TEXT,
    valor_estimado            REAL,
    contratacao               TEXT,
    dt_criacao_contratacao    TEXT,
    status_contrato           TEXT,
    modalidade                TEXT,
    vl_total_empenhado        REAL,
    chave_siga                TEXT,
    dt_criacao_nadsiga        TEXT,
    dt_emissao_nadsiga        TEXT,
    ano                       INTEGER,
    fonte_recurso             TEXT,
    natureza                  TEXT,
    valor_atual_contrato      REAL,
    valor_original            REAL,
    data_extracao             TEXT,
    FOREIGN KEY (contratacao) REFERENCES contratos(contratacao)
);

-- Sanções (projeção SANCOES.CSV). A FK confiável é fornecedor.
-- Não relacionar por contrato/processo.
CREATE TABLE IF NOT EXISTS sancoes (
    nome                 TEXT,
    cpf_cnpj             TEXT,
    cnpj_norm            TEXT,
    id_forn              INTEGER,
    enquadramento_legal  TEXT,
    numero_processo      TEXT,
    processo_norm        TEXT,
    dt_efetivacao        TEXT,
    prazo                TEXT,
    dt_inicio            TEXT,
    dt_final             TEXT,
    justificativa        TEXT,
    motivo               TEXT,
    orgao_apenador       TEXT,
    status               TEXT,
    data_extracao        TEXT,
    FOREIGN KEY (cnpj_norm) REFERENCES fornecedores(cnpj_norm)
);

-- Sanções (projeção FORNECEDOR_SANCOES.CSV — adiciona campo Contrato).
-- O campo `contrato` não é FK confiável para contratos e não deve ser usado em JOIN.
CREATE TABLE IF NOT EXISTS fornecedor_sancoes (
    nome                TEXT,
    cpf_cnpj            TEXT,
    cnpj_norm           TEXT,
    id_forn             INTEGER,
    orgao_apenador      TEXT,
    enquadramento_legal TEXT,
    motivo              TEXT,
    contrato            TEXT,
    dt_efetivacao       TEXT,
    status_penalidade   TEXT,
    data_extracao       TEXT,
    FOREIGN KEY (cnpj_norm) REFERENCES fornecedores(cnpj_norm)
);
