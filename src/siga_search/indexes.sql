-- Índices secundários — criados após ingestão (mais rápido)
CREATE INDEX IF NOT EXISTS idx_catalogo_familia ON catalogo(id_familia);
CREATE INDEX IF NOT EXISTS idx_catalogo_classe  ON catalogo(id_classe);
CREATE INDEX IF NOT EXISTS idx_catalogo_cod     ON catalogo(cod_item);

CREATE INDEX IF NOT EXISTS idx_fornecedores_nome ON fornecedores(nome);

CREATE INDEX IF NOT EXISTS idx_licit_processo ON licitacoes(processo_norm);
CREATE INDEX IF NOT EXISTS idx_licit_unidade  ON licitacoes(unidade);

CREATE INDEX IF NOT EXISTS idx_atas_id        ON atas_registro_preco(id_ata);
CREATE INDEX IF NOT EXISTS idx_atas_licit     ON atas_registro_preco(id_licitacao);
CREATE INDEX IF NOT EXISTS idx_atas_processo  ON atas_registro_preco(processo_norm);
CREATE INDEX IF NOT EXISTS idx_ataproc_processo ON ata_processos(processo_norm);

CREATE INDEX IF NOT EXISTS idx_contratos_contratacao ON contratos(contratacao);
CREATE INDEX IF NOT EXISTS idx_contratos_licit       ON contratos(id_licitacao);
CREATE INDEX IF NOT EXISTS idx_contratos_cnpj        ON contratos(cnpj_norm);
CREATE INDEX IF NOT EXISTS idx_contratos_processo    ON contratos(processo_norm);

CREATE INDEX IF NOT EXISTS idx_cd_processo ON compras_diretas(processo_norm);
CREATE INDEX IF NOT EXISTS idx_cd_cnpj     ON compras_diretas(cnpj_norm);
CREATE INDEX IF NOT EXISTS idx_cd_item     ON compras_diretas(id_item);
CREATE INDEX IF NOT EXISTS idx_cd_id_processo ON compras_diretas(id_processo);

CREATE INDEX IF NOT EXISTS idx_oc_processo ON outras_compras(processo_norm);
CREATE INDEX IF NOT EXISTS idx_oc_cnpj     ON outras_compras(cnpj_norm);
CREATE INDEX IF NOT EXISTS idx_oc_item     ON outras_compras(id_item);
CREATE INDEX IF NOT EXISTS idx_oc_id_processo ON outras_compras(id_processo);

CREATE INDEX IF NOT EXISTS idx_ped_id       ON ped(id_ped);
CREATE INDEX IF NOT EXISTS idx_ped_processo ON ped(processo_norm);
CREATE INDEX IF NOT EXISTS idx_ped_item     ON ped(id_item);

CREATE INDEX IF NOT EXISTS idx_itlic_licit ON itens_licitacoes(id_licitacao);
CREATE INDEX IF NOT EXISTS idx_itlic_item  ON itens_licitacoes(id_item);

CREATE INDEX IF NOT EXISTS idx_itata_ata  ON itens_atas_registro_preco(id_ata);
CREATE INDEX IF NOT EXISTS idx_itata_item ON itens_atas_registro_preco(id_item);
CREATE INDEX IF NOT EXISTS idx_itata_cnpj ON itens_atas_registro_preco(cnpj_norm);

CREATE INDEX IF NOT EXISTS idx_partata_ata  ON participantes_atas_registro_preco(id_ata);
CREATE INDEX IF NOT EXISTS idx_partata_item ON participantes_atas_registro_preco(id_item);

CREATE INDEX IF NOT EXISTS idx_itcontr_contr ON itens_contratos(contratacao);
CREATE INDEX IF NOT EXISTS idx_itcontr_ata   ON itens_contratos(id_ata);
CREATE INDEX IF NOT EXISTS idx_itcontr_item  ON itens_contratos(id_item);

CREATE INDEX IF NOT EXISTS idx_part_lic   ON participantes(id_lic);
CREATE INDEX IF NOT EXISTS idx_part_item  ON participantes(id_item);
CREATE INDEX IF NOT EXISTS idx_part_cnpj  ON participantes(cnpj_norm);
CREATE INDEX IF NOT EXISTS idx_part_venc  ON participantes(fornecedor_vencedor);

CREATE INDEX IF NOT EXISTS idx_fmap_cnpj ON fornecedor_mapeamentos(cnpj_norm);
CREATE INDEX IF NOT EXISTS idx_fmap_fam  ON fornecedor_mapeamentos(familia);

CREATE INDEX IF NOT EXISTS idx_fhc_cnpj  ON fornecedor_historico_contratacoes(cnpj_norm);
CREATE INDEX IF NOT EXISTS idx_fhc_contr ON fornecedor_historico_contratacoes(contratacao);

CREATE INDEX IF NOT EXISTS idx_hpa_item ON historico_precos_atas(id_item);
CREATE INDEX IF NOT EXISTS idx_hpa_ata_srp ON historico_precos_atas(ata_srp);
CREATE INDEX IF NOT EXISTS idx_hpcd_item  ON historico_precos_cd(id_item);
CREATE INDEX IF NOT EXISTS idx_hpcd_contr ON historico_precos_cd(contratacao);
CREATE INDEX IF NOT EXISTS idx_hpcd_processo ON historico_precos_cd(processo_norm);
CREATE INDEX IF NOT EXISTS idx_hpl_item  ON historico_precos_licit(id_item);
CREATE INDEX IF NOT EXISTS idx_hpl_contr ON historico_precos_licit(contratacao);

CREATE INDEX IF NOT EXISTS idx_assapc_contr    ON acompanhamento_assapc(contratacao);
CREATE INDEX IF NOT EXISTS idx_assapc_processo ON acompanhamento_assapc(processo_norm);
CREATE INDEX IF NOT EXISTS idx_assapc_chave    ON acompanhamento_assapc(chave_siga);

CREATE INDEX IF NOT EXISTS idx_sancoes_cnpj     ON sancoes(cnpj_norm);
CREATE INDEX IF NOT EXISTS idx_sancoes_processo ON sancoes(processo_norm);
CREATE INDEX IF NOT EXISTS idx_fsanc_cnpj ON fornecedor_sancoes(cnpj_norm);
