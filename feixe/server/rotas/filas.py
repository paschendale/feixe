"""B8: fila de folhas por pessoa. Só supervisor, na UF dele. A atribuição pela fila acontece no concluir (cargas)."""

from __future__ import annotations

import contextlib

from ...core.dados import ErroDados
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

    @r.rota("POST", "/api/distribuir/sugestao", exige=("supervisor",))
    def _sugestao(req):
        with ctx.tx() as ex:
            return 200, dfi.sugestao(ex, uf_de(ctx.eu()), campo(req, "lotes", lambda v: [int(x) for x in v]))

    @r.rota("POST", "/api/distribuir", exige=("supervisor",))
    def _distribuir(req):
        # Uma folha por pessoa (D-109): cada item entra na fila da pessoa, numa transação própria (a recusa de um não
        # impede os outros); quem está sem carga recebe na hora.
        uf = uf_de(ctx.eu())
        itens = campo(req, "itens", list)
        agora, na_fila, erros = [], [], []
        for it in itens:
            try:
                id_le, resp = int(it["id_lote_etapa"]), str(it["responsavel"])
            except (KeyError, TypeError, ValueError):
                raise ErroApi(400, "cada item precisa de id_lote_etapa e responsavel") from None
            try:
                with ctx.tx() as ex:
                    r = dfi.distribuir_uma(ex, uf, id_le, resp)
            except ErroDados as e:
                erros.append({"id_lote_etapa": id_le, "erro": e.mensagem})
                continue
            (agora if r.get("atribuida") else na_fila).append({"id_lote_etapa": id_le, "responsavel": resp,
                                                                "atribuida": r.get("atribuida")})  # fmt: skip
        if agora or na_fila:
            ctx.publicar("fila", {"distribuidas": len(agora) + len(na_fila)})
            ctx.publicar("carga", {"distribuidas": len(agora)})
            ctx.publicar("lote", {"distribuidas": len(agora)})
            with contextlib.suppress(ErroApi):
                ctx.qgis("cargas_mudaram", None)
        return 200, {"agora": agora, "na_fila": na_fila, "erros": erros}
