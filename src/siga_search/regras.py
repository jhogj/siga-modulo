"""Regras de negócio: constantes de status e situação derivada (fonte única).

`hoje` é sempre `date.today()`; a data de extração não entra nestas regras.
"""
from __future__ import annotations

from datetime import date

CANCELADOS = ("Cancelado", "Rejeitado")
TRAMITACAO = ("Aguard. Liberação", "Em Aprovação", "Aguardando publ. PNCP", "Em Alteração", "Em Edição")
LIC_HOMOLOGADAS = ("Homologado", "Homologado Parcial")
LIC_SEM_VENCEDOR = ("Fracassada", "Deserta")
LIC_CANCELADAS = ("Revogado", "Anulado")
LIC_SUSPENSAS = ("Suspensa",)
ATA_INTERROMPIDAS = ("Cancelada", "Suspensa", "Interrompida")
ALERTA_LICITACAO = LIC_SEM_VENCEDOR + LIC_CANCELADAS + LIC_SUSPENSAS
ALERTA_FORNECEDOR = ("Bloqueado", "Penalizado")
ALERTA_ITEM = ("Fracassado", "Deserto", "Anulado/Revogado", "FRACASSADO", "DESERTO", "ANULADO")

# Opções do 3º select por tipo. Chaves estáveis usadas na URL (?situacao=).
SITUACOES = {
    "contratos": {"rotulo": "Situação", "opcoes": [
        ("vigentes", "Vigentes"), ("encerrados", "Encerrados"),
        ("tramitacao", "Em tramitação"), ("cancelados", "Cancelados")]},
    "licitacoes": {"rotulo": "Situação", "opcoes": [
        ("homologadas", "Homologadas"), ("andamento", "Em andamento"),
        ("sem_vencedor", "Fracassadas ou desertas"), ("canceladas", "Revogadas ou anuladas"),
        ("suspensas", "Suspensas")]},
    "atas": {"rotulo": "Situação", "opcoes": [
        ("vigentes", "Vigentes"), ("encerradas", "Encerradas"),
        ("interrompidas", "Canceladas, suspensas ou interrompidas")]},
    "fornecedores": {"rotulo": "Situação", "opcoes": [
        ("sancao", "Com sanção vigente"), ("bloqueados", "Bloqueados"), ("penalizados", "Penalizados")]},
    "compras": {"rotulo": "Tipo de compra", "opcoes": [
        ("diretas", "Dispensa e inexigibilidade"), ("outras", "Adesões, renovações e outras")]},
    "itens": {"rotulo": "Tipo", "opcoes": [("material", "Materiais"), ("servico", "Serviços")]},
}


def _d(v) -> date | None:
    """ISO (com ou sem hora) → date; inválido ou vazio → None."""
    if v is None:
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _sit(texto: str, alerta: bool = False, grupo: str | None = None) -> dict:
    return {"texto": texto, "alerta": alerta, "grupo": grupo}


def situacao_contrato(status, dt_fim, hoje: date | None = None) -> dict:
    """Situação derivada do contrato: {texto, alerta, grupo}."""
    hoje = hoje or date.today()
    fim = _d(dt_fim)
    if status in CANCELADOS:
        return _sit("Cancelado", True, "cancelados")
    if status in TRAMITACAO:
        return _sit("Em tramitação", False, "tramitacao")
    if status == "Encerrado":
        if fim and fim <= hoje:
            return _sit(f"Encerrado em {_br(fim)}", False, "encerrados")
        return _sit("Encerrado", False, "encerrados")
    if fim is None:
        return _sit("Vigência não informada", False, "sem_vigencia")
    if fim >= hoje:
        return _sit(f"Vigente até {_br(fim)}", False, "vigentes")
    return _sit(f"Encerrado em {_br(fim)}", False, "encerrados")


def situacao_ata(status_ata, fim_validade, hoje: date | None = None) -> dict:
    """Situação derivada da ata. "Válida"/"Inválida" nunca aparecem."""
    hoje = hoje or date.today()
    if status_ata in ATA_INTERROMPIDAS:
        return _sit(status_ata, True, "interrompidas")
    fim = _d(fim_validade)
    if fim is None:
        return _sit("Validade não informada", False, None)
    if fim >= hoje:
        return _sit(f"Vigente até {_br(fim)}", False, "vigentes")
    return _sit(f"Encerrada em {_br(fim)}", False, "encerradas")


def situacao_sancao(status, dt_final, hoje: date | None = None) -> dict:
    """Situação da sanção: {texto, alerta, vigente}."""
    hoje = hoje or date.today()
    fim = _d(dt_final)
    if status == "Vigente":
        if fim is None:
            return {"texto": "Vigente por prazo indeterminado", "alerta": True, "vigente": True}
        if fim >= hoje:
            return {"texto": f"Vigente até {_br(fim)}", "alerta": True, "vigente": True}
        return {"texto": f"Encerrada em {_br(fim)}", "alerta": False, "vigente": False}
    return {"texto": status or "", "alerta": False, "vigente": False}


def alerta_licitacao(status) -> bool:
    return status in ALERTA_LICITACAO


def alerta_fornecedor(situacao) -> bool:
    return situacao in ALERTA_FORNECEDOR


def alerta_item(situacao_item) -> bool:
    return situacao_item in ALERTA_ITEM
