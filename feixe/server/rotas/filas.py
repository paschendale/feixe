"""B8: fila de folhas por pessoa. Só supervisor, na UF dele. A atribuição pela fila acontece no concluir (cargas)."""

from __future__ import annotations

import contextlib

from ...core.dados import filas as dfi
from ..api import ErroApi, campo, inteiro
from .lotes import uf_de


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/filas", exige=("supervisor",))
    def _lista(req):
        with ctx.tx() as ex:
            return 200, dfi.listar(ex, uf_de(ctx.eu()))

    @r.rota("POST", "/api/filas", exige=("supervisor",))
    def _adicionar(req):
        with ctx.tx() as ex:
            item = dfi.adicionar(ex, uf_de(ctx.eu()), campo(req, "responsavel", str), campo(req, "id_lote_etapa", int))
        ctx.publicar("fila", {"adicionado": item["id"]})
        if item.get("atribuida"):
            ctx.publicar("carga", {"fila": item["atribuida"]})
            ctx.publicar("lote", {"fila": item["atribuida"]["id_lote"]})
            with contextlib.suppress(ErroApi):
                ctx.qgis("cargas_mudaram", None)
        return 200, item

    @r.rota("PUT", "/api/filas/ordem", exige=("supervisor",))
    def _reordenar(req):
        ids = campo(req, "ids", lambda v: [int(x) for x in v])
        with ctx.tx() as ex:
            dfi.reordenar(ex, uf_de(ctx.eu()), campo(req, "responsavel", str), ids)
        ctx.publicar("fila", {"reordenada": True})
        return 200, {"ok": True}

    @r.rota("DELETE", "/api/filas/{id}", exige=("supervisor",))
    def _remover(req):
        with ctx.tx() as ex:
            dfi.remover(ex, uf_de(ctx.eu()), inteiro(req.params["id"]))
        ctx.publicar("fila", {"removido": True})
        return 200, {"ok": True}
