"""B2: minhas cargas. As funções de módulo servem às rotas e aos botões da barra do Feixe (mesmo caminho)."""

from __future__ import annotations

import contextlib
from typing import Dict, Optional

from ...core.dados import ErroDados
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


def gerar(ctx, ids_lote_etapa, previa: bool, uf: Optional[str]) -> Dict:
    """Gera (ou só mostra) as cargas de várias passagens. Cada passagem vai na sua transação: a recusa de uma não
    impede as outras, e volta em `erros`. Na prévia, as células aparecem no QGIS numa camada temporária."""
    resultados, erros, celulas = [], [], []
    for id_le in ids_lote_etapa:
        try:
            with ctx.tx() as ex:
                r = dc.gerar_pela_grade(ex, id_le, previa, uf)
        except ErroDados as e:
            erros.append({"id_lote_etapa": id_le, "erro": e.mensagem})
            continue
        for c in r.pop("previa", []):
            celulas.append({**c, "folha": r["folha_revisao"]})
        resultados.append(r)
    if previa and celulas:
        _no_qgis(ctx, "previa_cargas", celulas)
    if not previa and resultados:
        ctx.publicar("carga", {"geradas": [r["id_lote_etapa"] for r in resultados]})
        ctx.publicar("lote", {"cargas_geradas": [r["id_lote_etapa"] for r in resultados]})
        _no_qgis(ctx, "cargas_geradas")
    return {"resultados": resultados, "erros": erros}


def registrar(r, ctx) -> None:
    @r.rota("GET", "/api/equipe", exige=("supervisor",))
    def _equipe(req):
        from .lotes import uf_de

        projeto = req.query.get("projeto")
        with ctx.tx() as ex:
            return 200, {"itens": dc.equipe(ex, uf_de(ctx.eu()), inteiro(projeto, "projeto") if projeto else None)}

    @r.rota("POST", "/api/cargas/atribuir", exige=("supervisor",))
    def _atribuir(req):
        from .lotes import uf_de

        lista = lambda v: [int(x) for x in v]  # noqa: E731
        with ctx.tx() as ex:
            res = dc.atribuir(
                ex, uf_de(ctx.eu()), campo(req, "responsavel", str, padrao=None), campo(req, "ids", lista, padrao=None),
                campo(req, "lote_etapas", lista, padrao=None), campo(req, "so_disponiveis", bool, padrao=False),
                campo(req, "de", str, padrao=None),
            )  # fmt: skip
        if res["atribuidas"]:
            ctx.publicar("carga", {"atribuidas": res["atribuidas"]})
            ctx.publicar("lote", {"atribuidas": res["atribuidas"]})
            _no_qgis(ctx, "cargas_mudaram", None)
        return 200, res

    @r.rota("POST", "/api/cargas/dividir", exige=("supervisor",))
    def _dividir(req):
        from .lotes import uf_de

        previa = campo(req, "previa", bool, padrao=True)
        with ctx.tx() as ex:
            res = dc.dividir(ex, uf_de(ctx.eu()), campo(req, "id_lote_etapa", int), campo(req, "pessoas", list), previa)
        if not previa:
            ctx.publicar("carga", {"divididas": res["disponiveis"]})
            ctx.publicar("lote", {"divididas": res["disponiveis"]})
            _no_qgis(ctx, "cargas_mudaram", None)
        return 200, res

    @r.rota("POST", "/api/qgis/selecao_cargas", exige=("supervisor",))
    def _selecao(req):
        # Cargas selecionadas no QGIS (em qualquer camada do grupo Feixe que tenha as cargas).
        return 200, ctx.qgis("selecao_cargas")

    @r.rota("POST", "/api/cargas/gerar", exige=("supervisor",))
    def _gerar(req):
        from .lotes import uf_de

        ids = campo(req, "lote_etapas", lambda v: [int(x) for x in v])
        if not ids:
            raise ErroApi(400, "escolha pelo menos uma passagem")
        return 200, gerar(ctx, ids, campo(req, "previa", bool, padrao=True), uf_de(ctx.eu()))

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
