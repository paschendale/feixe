"""B2: minhas cargas. As funções de módulo servem às rotas e aos botões da barra do Feixe (mesmo caminho)."""

from __future__ import annotations

import contextlib
from typing import Dict, Optional

from ...core.dados import cargas as dc
from ..api import ErroApi, campo, inteiro

# Quem pode ter carga atribuída. Consulta só olha.
EXECUTORES = ("apm", "avaliador", "supervisor")


def _no_qgis(ctx, nome: str, *args) -> None:
    """Ação no QGIS quando ele está lá (no painel de teste, sem QGIS, segue sem ela)."""
    with contextlib.suppress(ErroApi):
        ctx.qgis(nome, *args)


def _mudou(ctx, r: Dict) -> Dict:
    ctx.publicar("carga", {"id": r["carga"]["id"], "concluido": r["carga"]["concluido"], "progresso": r["progresso"]})
    _no_qgis(ctx, "cargas_mudaram", r["progresso"])
    return r


def concluir(ctx, id_carga: int) -> Dict:
    with ctx.tx() as ex:
        r = dc.concluir(ex, id_carga)
    return _mudou(ctx, r)


def desfazer(ctx, id_carga: int) -> Dict:
    with ctx.tx() as ex:
        r = dc.desfazer(ex, id_carga)
    return _mudou(ctx, r)


def focar(ctx, id_carga: int) -> Dict:
    with ctx.tx() as ex:
        carga = dc.uma(ex, id_carga)
        if not carga:
            raise ErroApi(404, "carga não encontrada")
        progresso = dc.progresso(ex, carga["id_lote_etapa"])
    carga.pop("responsavel", None)
    ctx.qgis("focar_carga", carga, progresso)
    return {"carga": carga, "progresso": progresso}


def proxima(ctx, referencia: Optional[int] = None) -> Dict:
    """Próxima carga pendente; no QGIS, seleciona e enquadra. Sem pendentes: carga nula."""
    with ctx.tx() as ex:
        carga = dc.proxima(ex, referencia)
        progresso = dc.progresso(ex, carga["id_lote_etapa"]) if carga else None
    if carga:
        _no_qgis(ctx, "focar_carga", carga, progresso)
    return {"carga": carga, "progresso": progresso}


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/cargas", exige=EXECUTORES)
    def _lista(req):
        le = req.query.get("lote_etapa")
        situacao = req.query.get("situacao")
        concluido = {"pendente": False, "concluida": True}.get(situacao or "")
        if situacao and concluido is None:
            raise ErroApi(400, "situacao deve ser pendente ou concluida")
        with ctx.tx() as ex:
            return 200, {"itens": dc.minhas(ex, inteiro(le, "lote_etapa") if le else None, concluido)}

    @r.rota("GET", "/api/cargas/resumo", exige=EXECUTORES)
    def _resumo(req):
        with ctx.tx() as ex:
            return 200, dc.resumo(ex)

    @r.rota("POST", "/api/cargas/proxima", exige=EXECUTORES)
    def _proxima(req):
        return 200, proxima(ctx, campo(req, "referencia", int, padrao=None))

    @r.rota("POST", "/api/cargas/{id}/concluir", exige=EXECUTORES)
    def _concluir(req):
        return 200, concluir(ctx, inteiro(req.params["id"]))

    @r.rota("POST", "/api/cargas/{id}/desfazer", exige=EXECUTORES)
    def _desfazer(req):
        return 200, desfazer(ctx, inteiro(req.params["id"]))

    @r.rota("POST", "/api/cargas/{id}/zoom", exige=EXECUTORES)
    def _zoom(req):
        return 200, focar(ctx, inteiro(req.params["id"]))
