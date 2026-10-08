"""Fachada dos detalhes por entidade.

O import é preguiçoso: um módulo de página quebrado não derruba as outras páginas.
"""
import importlib
import sys
import types


def _m(nome): return importlib.import_module(f"{__name__}.{nome}")


def contrato(conn, contratacao):                     return _m("contrato").get(conn, contratacao)
def contrato_secao(conn, contratacao, nome, pagina): return _m("contrato").secao(conn, contratacao, nome, pagina)
def fornecedor(conn, cnpj_norm):                     return _m("fornecedor").get(conn, cnpj_norm)
def fornecedor_secao(conn, cnpj_norm, nome, pagina): return _m("fornecedor").secao(conn, cnpj_norm, nome, pagina)
def fornecedor_chave_antiga(conn, digitos):          return _m("fornecedor").chave_antiga(conn, digitos)
def licitacao(conn, id_licitacao):                   return _m("licitacao").get(conn, id_licitacao)
def licitacao_secao(conn, id_licitacao, nome, pagina): return _m("licitacao").secao(conn, id_licitacao, nome, pagina)
def ata(conn, id_ata):                               return _m("ata").get(conn, id_ata)
def ata_secao(conn, id_ata, nome, pagina):           return _m("ata").secao(conn, id_ata, nome, pagina)
def compra(conn, id_processo):                       return _m("compra").get(conn, id_processo)
def compra_secao(conn, id_processo, nome, pagina):   return _m("compra").secao(conn, id_processo, nome, pagina)
def item(conn, id_item, origem=None, pagina=1):      return _m("item").get(conn, id_item, origem=origem, pagina=pagina)
def item_secao(conn, id_item, nome, pagina):         return _m("item").secao(conn, id_item, nome, pagina)  # sempre None


_FACHADA = frozenset({"contrato", "fornecedor", "licitacao", "ata", "compra", "item"})


class _Pacote(types.ModuleType):
    """Todo import de um submódulo (inclusive `from .ata import get` dentro de outro módulo) grava
    o módulo como atributo do pacote (details.ata = <módulo>) e apagaria a função de mesmo nome.
    O pacote recusa essa gravação; o submódulo continua em sys.modules."""

    def __setattr__(self, nome, valor):
        if nome in _FACHADA and isinstance(valor, types.ModuleType):
            return
        super().__setattr__(nome, valor)


sys.modules[__name__].__class__ = _Pacote
