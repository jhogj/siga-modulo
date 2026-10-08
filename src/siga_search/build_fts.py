"""Constrói os índices FTS5 a partir das tabelas relacionais."""
from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path


def _exec(conn: sqlite3.Connection, label: str, sql: str, params: tuple = ()) -> None:
    t0 = time.time()
    cur = conn.execute(sql, params)
    n = cur.rowcount
    conn.commit()
    print(f"  ✓ {label}: {n:,} docs em {time.time() - t0:.1f}s", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("data/siga.db"))
    args = parser.parse_args(argv)

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = OFF;")
    conn.execute("PRAGMA temp_store = MEMORY;")
    conn.execute("PRAGMA cache_size = -200000;")

    print("→ Criando tabelas virtuais FTS5…", flush=True)
    fts_path = Path(__file__).parent / "fts.sql"
    conn.executescript(fts_path.read_text())
    conn.commit()

    total_t0 = time.time()

    # ---------------------------------------------------------------- itens
    print("→ Indexando itens (com última atividade)…", flush=True)
    # Pré-calcula última atividade por id_item
    conn.execute("""
        CREATE TEMP TABLE tmp_item_dt AS
        SELECT id_item, MAX(d) AS dt FROM (
            SELECT id_item, dt_homologacao_licit AS d
            FROM itens_licitacoes WHERE id_item IS NOT NULL
            UNION ALL
            SELECT id_item, dt_aprovacao FROM compras_diretas WHERE id_item IS NOT NULL
            UNION ALL
            SELECT id_item, dt_aprovacao FROM outras_compras WHERE id_item IS NOT NULL
            UNION ALL
            SELECT id_item, inicio_disputa FROM ped WHERE id_item IS NOT NULL
            UNION ALL
            SELECT id_item, dt_homologacao FROM historico_precos_licit WHERE id_item IS NOT NULL
            UNION ALL
            SELECT id_item, dt_aprovacao FROM historico_precos_cd WHERE id_item IS NOT NULL
            UNION ALL
            SELECT i.id_item, a.fim_validade
            FROM itens_atas_registro_preco i
            LEFT JOIN atas_registro_preco a USING (id_ata)
            WHERE i.id_item IS NOT NULL
        )
        WHERE d IS NOT NULL
        GROUP BY id_item
    """)
    conn.execute("CREATE INDEX tmp_item_dt_idx ON tmp_item_dt(id_item)")
    _exec(conn, "fts_item", """
        INSERT INTO fts_item (body, id_item, cod_item, tipo, familia, classe, descricao, dt)
        SELECT
            coalesce(c.descricao, '') || ' ' ||
            coalesce(c.tipo, '') || ' ' ||
            coalesce(c.familia, '') || ' ' ||
            coalesce(c.classe, '') || ' ' ||
            coalesce(c.artigo, '') || ' ' ||
            coalesce(c.cod_item, ''),
            c.id_item, c.cod_item, c.tipo, c.familia, c.classe, c.descricao,
            t.dt
        FROM catalogo c
        LEFT JOIN tmp_item_dt t USING (id_item)
    """)
    conn.execute("DROP TABLE tmp_item_dt")

    # ----------------------------------------------------------- fornecedor
    print("→ Indexando fornecedores (com último contrato)…", flush=True)
    conn.execute("""
        CREATE TEMP TABLE tmp_fmap AS
        SELECT cnpj_norm,
               group_concat(DISTINCT familia) AS familias,
               group_concat(DISTINCT classe)  AS classes
        FROM fornecedor_mapeamentos
        WHERE cnpj_norm IS NOT NULL
        GROUP BY cnpj_norm
    """)
    conn.execute("CREATE INDEX tmp_fmap_idx ON tmp_fmap(cnpj_norm)")
    conn.execute("""
        CREATE TEMP TABLE tmp_forn_dt AS
        SELECT cnpj_norm, MAX(d) AS dt FROM (
            SELECT cnpj_norm, dt_contratacao AS d FROM contratos WHERE cnpj_norm IS NOT NULL
            UNION ALL
            SELECT cnpj_norm, dt_aprovacao FROM compras_diretas WHERE cnpj_norm IS NOT NULL
            UNION ALL
            SELECT cnpj_norm, dt_aprovacao FROM outras_compras WHERE cnpj_norm IS NOT NULL
        )
        WHERE d IS NOT NULL
        GROUP BY cnpj_norm
    """)
    conn.execute("CREATE INDEX tmp_forn_dt_idx ON tmp_forn_dt(cnpj_norm)")
    _exec(conn, "fts_fornecedor", """
        INSERT INTO fts_fornecedor (body, cnpj_norm, cpf_cnpj, nome, cidade, uf, situacao, dt)
        SELECT
            coalesce(f.nome, '') || ' ' ||
            coalesce(f.cpf_cnpj, '') || ' ' ||
            coalesce(f.cidade, '') || ' ' ||
            coalesce(f.uf, '') || ' ' ||
            coalesce(m.familias, '') || ' ' ||
            coalesce(m.classes, ''),
            f.cnpj_norm, f.cpf_cnpj, f.nome, f.cidade, f.uf, f.situacao,
            coalesce(d.dt, f.data_cadastro)
        FROM fornecedores f
        LEFT JOIN tmp_fmap m USING (cnpj_norm)
        LEFT JOIN tmp_forn_dt d USING (cnpj_norm)
    """)
    conn.execute("DROP TABLE tmp_fmap")
    conn.execute("DROP TABLE tmp_forn_dt")

    # ------------------------------------------------------------ licitacao
    print("→ Indexando licitações…", flush=True)
    _exec(conn, "fts_licitacao", """
        INSERT INTO fts_licitacao (body, id_licitacao, licitacao, unidade, objeto, modalidade, status, processo, dt)
        SELECT
            coalesce(licitacao, '') || ' ' ||
            coalesce(objeto, '') || ' ' ||
            coalesce(unidade, '') || ' ' ||
            coalesce(processo, '') || ' ' ||
            coalesce(modalidade, ''),
            id_licitacao, licitacao, unidade, objeto, modalidade, status, processo,
            coalesce(dt_homologacao, dt_publicacao)
        FROM licitacoes
    """)

    # ----------------------------------------------------------------- ata
    print("→ Indexando atas (com todos os processos)…", flush=True)
    _exec(conn, "fts_ata", """
        INSERT INTO fts_ata (body, id_ata, numero_ata, unidade, objeto, status, processo, dt)
        SELECT
            coalesce(a.numero_ata, '') || ' ' ||
            coalesce(a.objeto, '') || ' ' ||
            coalesce(a.unidade_gerenciadora, '') || ' ' ||
            coalesce(a.licitacao_sigla, '') || ' ' ||
            coalesce(p.processos, a.processo, ''),
            a.id_ata, a.numero_ata, a.unidade_gerenciadora, a.objeto, a.status_ata,
            coalesce(p.processos, a.processo),
            coalesce(a.fim_validade, a.inicio_validade)
        FROM atas_registro_preco a
        LEFT JOIN (
            SELECT id_ata, group_concat(processo) AS processos
            FROM ata_processos
            GROUP BY id_ata
        ) p USING (id_ata)
    """)

    # ------------------------------------------------------------ contrato
    print("→ Indexando contratos…", flush=True)
    _exec(conn, "fts_contrato", """
        INSERT INTO fts_contrato (body, codigo_contrato, contratacao, unidade, objeto, fornecedor, cnpj_norm, status, processo, dt)
        SELECT
            coalesce(contratacao, '') || ' ' ||
            coalesce(objeto, '') || ' ' ||
            coalesce(unidade, '') || ' ' ||
            coalesce(fornecedor, '') || ' ' ||
            coalesce(cpf_cnpj, '') || ' ' ||
            coalesce(processo, ''),
            codigo_contrato, contratacao, unidade, objeto, fornecedor,
            cnpj_norm, status_contratacao, processo,
            dt_contratacao
        FROM contratos
    """)

    # -------------------------------------------------------------- compra
    print("→ Indexando compras (CD + outras; PED é detalhe por processo)…", flush=True)
    _exec(conn, "fts_compra", """
        INSERT INTO fts_compra (body, src, src_id, unidade, processo, objeto, fornecedor, cnpj_norm, valor, dt)
        SELECT
            coalesce(objeto, '') || ' ' ||
            coalesce(fornecedor_vencedor, '') || ' ' ||
            coalesce(unidade, '') || ' ' ||
            coalesce(item, '') || ' ' ||
            coalesce(processo, ''),
            'compras_diretas', cast(rowid as text), unidade, processo, objeto,
            fornecedor_vencedor, cnpj_norm,
            cast(coalesce(valor_processo, 0) as text),
            dt_aprovacao
        FROM compras_diretas
        UNION ALL
        SELECT
            coalesce(objeto, '') || ' ' ||
            coalesce(fornecedor_vencedor, '') || ' ' ||
            coalesce(unidade, '') || ' ' ||
            coalesce(item, '') || ' ' ||
            coalesce(processo, ''),
            'outras_compras', cast(rowid as text), unidade, processo, objeto,
            fornecedor_vencedor, cnpj_norm,
            cast(coalesce(valor_processo, 0) as text),
            dt_aprovacao
        FROM outras_compras
    """)

    print("→ Otimizando índices…", flush=True)
    for tbl in ("fts_item", "fts_fornecedor", "fts_licitacao",
                "fts_ata", "fts_contrato", "fts_compra"):
        conn.execute(f"INSERT INTO {tbl}({tbl}) VALUES('optimize')")
    conn.commit()

    print(f"\nFTS construído em {time.time() - total_t0:.1f}s.")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
