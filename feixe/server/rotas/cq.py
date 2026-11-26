"""D2: planos de amostragem do CQ numa passagem. Só o supervisor cria ou refaz; na CCAR, como o resto da supervisão.

Registrado antes de `fluxos`, porque `POST /api/lote_etapas/{id}/{acao}` (iniciar, concluir...) casaria também com
`/cq_plano`."""

from __future__ import annotations

from ...core.dados import cq as dq
from ..api import ErroApi, campo, inteiro
from .cargas import _no_qgis
from .lotes import uf_de


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    raise ValueError(v)


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/lote_etapas/{id}/cq_planos", exige=("supervisor",))
    def _planos(req):
        with ctx.tx() as ex:
            return 200, dq.planos(ex, uf_de(ctx.eu()), inteiro(req.params["id"]))

    @r.rota("POST", "/api/lote_etapas/{id}/cq_plano", exige=("supervisor",))
    def _plano(req):
        id_le = inteiro(req.params["id"])
        previa = campo(req, "previa", _bool, padrao=False)
        semente = campo(req, "semente", int, padrao=None)
        if semente is not None and semente <= 0:
            raise ErroApi(400, "semente inválida")
        with ctx.tx() as ex:
            res = dq.criar_plano(
                ex, uf_de(ctx.eu()), id_le, campo(req, "id_atividade", int), campo(req, "nivel"), campo(req, "lqa"),
                campo(req, "fracao_critica", padrao=None), previa=previa,
                refazer=campo(req, "refazer", _bool, padrao=False), semente=semente,
            )  # fmt: skip
        if not previa:
            # As amostras são cargas da passagem: o painel (gaveta, Distribuir) e as camadas do QGIS acompanham.
            ctx.publicar("carga", {"geradas": [id_le]})
            ctx.publicar("lote", {"cq_plano": id_le})
            _no_qgis(ctx, "cargas_geradas")
        return 200, res
