"""Utilitários comuns às páginas de detalhe."""
from __future__ import annotations

PREVIA = 10            # linhas mostradas numa seção da página quando total > MOSTRAR_TUDO_ATE
MOSTRAR_TUDO_ATE = 15  # se total <= 15, mostra tudo e não há "Ver todos"
POR_PAGINA = 25        # linhas por página nas listas completas (/{secao}) e nos resultados


def corte(total: int) -> int:
    return total if total <= MOSTRAR_TUDO_ATE else PREVIA


def paginar(total: int, pagina: int, por_pagina: int = POR_PAGINA) -> dict:
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(1, int(pagina or 1)), paginas)
    inicio = (pagina - 1) * por_pagina
    return {"pagina": pagina, "paginas": paginas, "total": total, "por_pagina": por_pagina,
            "offset": inicio, "inicio": inicio + 1 if total else 0,
            "fim": min(total, inicio + por_pagina)}


def vencedor(conn, id_lic, id_item, lote) -> tuple[str | None, str | None, int]:
    """Vencedor de um item de licitação: (nome, cnpj_norm, quantos outros fornecedores venceram).

    O mesmo id_item pode estar em mais de um lote: valem só os vencedores do mesmo lote (itens_lotes);
    lote fracassado ou deserto fica sem vencedor. Com mais de um, fica o primeiro em ordem alfabética.
    """
    rows = conn.execute(
        "SELECT fornecedor, cnpj_norm FROM participantes WHERE id_lic = ? AND id_item = ? "
        "AND fornecedor_vencedor = 'Sim' AND (? IS NULL OR itens_lotes = ?) ORDER BY fornecedor, cnpj_norm",
        (id_lic, id_item, lote, lote)).fetchall()
    distintos: dict = {}
    for nome, cnpj in rows:
        if nome or cnpj:
            distintos.setdefault(cnpj or nome, (nome, cnpj))
    if not distintos:
        return None, None, 0
    nome, cnpj = next(iter(distintos.values()))
    return nome, cnpj, len(distintos) - 1


def cnpj_por_nome(conn, nome: str, id_licitacao: int | None = None) -> str | None:
    """Fornecedor citado só pelo nome (itens de ata sem chave, layout antigo): chave por nome."""
    if not nome:
        return None
    if id_licitacao:
        r = conn.execute("SELECT cnpj_norm FROM participantes WHERE id_lic = ? AND fornecedor = ? "
                         "AND cnpj_norm IS NOT NULL LIMIT 1", (id_licitacao, nome)).fetchone()
        if r:
            return r[0]
    rows = conn.execute("SELECT cnpj_norm FROM fornecedores WHERE nome = ? LIMIT 2", (nome,)).fetchall()
    return rows[0][0] if len(rows) == 1 else None
