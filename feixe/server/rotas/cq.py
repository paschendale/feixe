"""CQ. D2: planos de amostragem numa passagem; só o supervisor cria ou refaz, na CCAR, como o resto da supervisão.
D3a: a execução do CQ (amostras, ocorrências, ciência) sobre o workspace, online ou offline, como minhas cargas
(D-111, D-123); cada escrita acorda a sincronização. As ocorrências da folha para o supervisor leem a CCAR.

Registrado antes de `fluxos`, porque `POST /api/lote_etapas/{id}/{acao}` (iniciar, concluir...) casaria também com
`/cq_plano`."""

from __future__ import annotations

import re
from typing import Dict

from ...core.dados import cq as dq
from ...core.dados.local import cq as lq
from ..api import ErroApi, campo, inteiro
from .cargas import EXECUTORES, _no_qgis, _publicar
from .lotes import uf_de

_UUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def _uuid(v: str) -> str:
    if not _UUID.match(v or ""):
        raise ErroApi(400, "ocorrência inválida")
    return v.lower()


def _bool(v) -> bool:
    if isinstance(v, bool):
        return v
    raise ValueError(v)


def _status(v) -> int:
    if isinstance(v, bool) or v not in (0, 1):
        raise ValueError(v)
    return int(v)


def _num(v) -> float:
    if isinstance(v, bool):
        raise ValueError(v)
    return float(v)


def _mudou_cq(ctx, dados: Dict, progresso=None) -> None:
    """Depois de uma escrita do CQ no workspace: o painel recarrega (`cq`) e as camadas do workspace mostram já."""
    ctx.publicar("cq", dados)
    _no_qgis(ctx, "cargas_mudaram", progresso, True)


def avaliar(ctx, id_amostra: int, status: int, observacao=lq._NADA) -> Dict:
    """Avaliar a amostra (rota e, no D3c, a barra do Feixe): a carga de CQ conclui e a resposta aponta a próxima."""
    ctx.exigir_pronto()
    with ctx.local() as ex:
        r = lq.avaliar(ex, id_amostra, status, observacao)
    _publicar(ctx, r)
    _mudou_cq(ctx, {"amostra": id_amostra, "status": status}, r["progresso"])
    return r


def registrar_ocorrencia(ctx, x, y, id_carga: int, anotacao=None) -> Dict:
    ctx.exigir_pronto()
    with ctx.local() as ex:
        r = lq.registrar(ex, x, y, id_carga, anotacao)
    _mudou_cq(ctx, {"ocorrencia": r["ocorrencia"]["uuid"], "registrada": True})
    return r


def registrar(r, ctx) -> None:
    # --- execução sobre o workspace (D3a) ---

    @r.rota("GET", "/api/amostras", exige=EXECUTORES)
    def _amostras(req):
        le = req.query.get("lote_etapa")
        situacao = req.query.get("situacao")
        pendente = {"pendente": True, "avaliada": False}.get(situacao or "")
        if situacao and pendente is None:
            raise ErroApi(400, "situacao deve ser pendente ou avaliada")
        id_le = inteiro(le, "lote_etapa") if le else None
        if ctx.preparando():
            return 200, {"itens": [], "preparando": True}
        with ctx.leitura() as ex:
            return 200, {"itens": lq.amostras(ex, id_le, pendente)}

    @r.rota("POST", "/api/amostras/{id}", exige=EXECUTORES)
    def _avaliar(req):
        corpo = req.corpo if isinstance(req.corpo, dict) else {}
        obs = corpo.get("observacao", lq._NADA)
        return 200, avaliar(ctx, inteiro(req.params["id"]), campo(req, "status", _status), obs)

    @r.rota("GET", "/api/inspecoes", exige=EXECUTORES)
    def _inspecoes(req):
        lote, le = req.query.get("id_lote"), req.query.get("id_lote_etapa")
        if ctx.preparando():
            return 200, {"itens": [], "preparando": True}
        with ctx.leitura() as ex:
            itens = lq.ocorrencias(
                ex, inteiro(lote, "id_lote") if lote else None, inteiro(le, "id_lote_etapa") if le else None
            )
        return 200, {"itens": itens}

    @r.rota("POST", "/api/inspecoes", exige=EXECUTORES)
    def _registrar(req):
        return 200, registrar_ocorrencia(
            ctx, campo(req, "x", _num), campo(req, "y", _num), campo(req, "id_carga_trabalho", int),
            campo(req, "anotacao", padrao=None),
        )  # fmt: skip

    @r.rota("POST", "/api/inspecoes/{uuid}", exige=EXECUTORES)
    def _editar(req):
        u = _uuid(req.params["uuid"])
        corpo = req.corpo if isinstance(req.corpo, dict) else {}
        anotacao = corpo.get("anotacao", lq._NADA)
        x, y = campo(req, "x", _num, padrao=None), campo(req, "y", _num, padrao=None)
        if (x is None) != (y is None):
            raise ErroApi(400, "para mudar o ponto, informe x e y")
        ctx.exigir_pronto()
        with ctx.local() as ex:
            res = lq.editar(ex, u, anotacao, x, y)
        _mudou_cq(ctx, {"ocorrencia": u})
        return 200, res

    @r.rota("DELETE", "/api/inspecoes/{uuid}", exige=EXECUTORES)
    def _apagar(req):
        u = _uuid(req.params["uuid"])
        ctx.exigir_pronto()
        with ctx.local() as ex:
            res = lq.apagar(ex, u)
        _mudou_cq(ctx, {"ocorrencia": u, "apagada": True})
        return 200, res

    @r.rota("POST", "/api/inspecoes/{uuid}/ciente", exige=EXECUTORES)
    def _ciente(req):
        u = _uuid(req.params["uuid"])
        ctx.exigir_pronto()
        with ctx.local() as ex:
            res = lq.ciente(ex, u)
        _mudou_cq(ctx, {"ocorrencia": u, "ciente": True})
        return 200, res

    # --- supervisão, na CCAR ---

    @r.rota("GET", "/api/lotes/{id}/ocorrencias", exige=("supervisor",))
    def _do_lote(req):
        with ctx.tx() as ex:
            return 200, dq.ocorrencias_do_lote(ex, uf_de(ctx.eu()), inteiro(req.params["id"]))

    # --- planos (D2), na CCAR ---

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
