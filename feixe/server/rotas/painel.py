"""Painel no navegador (D-103): Início por papel, "Esperando você" e a próxima etapa em várias folhas (D-109)."""

from __future__ import annotations

from typing import Dict, List

from ...core.dados import fluxos as df
from ...core.dados import painel as dp
from ...core.dados.local import cargas as lc
from ..api import ErroApi, campo, fuso_de
from .cargas import EXECUTORES, preparar
from .lotes import uf_de


def _abertas(ctx, uf: str, r: Dict) -> Dict:
    if r["abertas"]:
        ctx.publicar("lote", {"acao": "passagem", "ids": [a["id_lote"] for a in r["abertas"]]})
        r["preparo"] = preparar(ctx, uf, [a["id_lote_etapa"] for a in r["abertas"]])
    return r


def avancar(ctx, uf: str, ids: List[int], observacao: str, previa: bool) -> Dict:
    """Próxima etapa em várias folhas (D-109): conclui a etapa em andamento, abre a seguinte e prepara as cargas."""
    with ctx.tx() as ex:
        r = df.avancar(ex, uf, ids, observacao, previa)
    return r if previa else _abertas(ctx, uf, r)


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/painel/supervisao", exige=("supervisor", "gerente"))
    def _supervisao(req):
        with ctx.tx() as ex:
            return 200, dp.supervisao(ex, uf_de(ctx.eu(), True))

    @r.rota("GET", "/api/painel/esperando", exige=("supervisor",))
    def _esperando(req):
        with ctx.tx() as ex:
            return 200, {"grupos": dp.esperando(ex, uf_de(ctx.eu()))}

    @r.rota("GET", "/api/painel/execucao", exige=EXECUTORES)
    def _execucao(req):
        tz = fuso_de(req)
        # Execução: do workspace, como Minhas cargas (C3).
        if ctx.preparando():
            return 200, {"por_dia": [], "preparando": True}
        with ctx.leitura() as ex:
            return 200, lc.execucao(ex, tz)

    @r.rota("POST", "/api/lotes/avancar", exige=("supervisor",))
    def _avancar(req):
        ids = campo(req, "lotes", lambda v: [int(x) for x in v])
        if not ids:
            raise ErroApi(400, "escolha pelo menos uma folha")
        previa = campo(req, "previa", bool, padrao=True)
        return 200, avancar(ctx, uf_de(ctx.eu()), ids, campo(req, "observacao", str, padrao=""), previa)
