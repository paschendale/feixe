"""Painel no navegador (D-103): Início por papel, "Esperando você" e abrir a próxima etapa em várias folhas."""

from __future__ import annotations

from typing import Dict, List

from ...core.dados import ErroDados
from ...core.dados import fluxos as df
from ...core.dados import painel as dp
from ..api import ErroApi, campo
from .cargas import EXECUTORES
from .lotes import uf_de


def abrir_proximas(ctx, uf: str, ids: List[int], observacao: str) -> Dict:
    """Abre a etapa sugerida em cada folha, cada uma na sua transação: a recusa de uma não impede as outras.
    É o mesmo gesto da gaveta (nova passagem com observação), repetido; nada anda sem o supervisor pedir."""
    abertas, erros = [], []
    for id_lote in ids:
        try:
            with ctx.tx() as ex:
                existe = ex.um("SELECT 1 AS ok FROM mapcartacomp.lote WHERE id = %s", (id_lote,))
                estado = df.estado(ex, id_lote) if existe else None
                if not estado or not estado.get("sugestao"):
                    raise ErroDados("sem próxima etapa no fluxo")
                novo = df.nova_passagem(ex, uf, id_lote, estado["sugestao"]["id"], observacao)
            abertas.append({"id_lote": id_lote, "etapa": novo.get("etapa")})
        except ErroDados as e:
            erros.append({"id_lote": id_lote, "erro": e.mensagem})
    if abertas:
        ctx.publicar("lote", {"acao": "passagem", "ids": [a["id_lote"] for a in abertas]})
    return {"abertas": abertas, "erros": erros}


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
        fuso = req.query.get("fuso") or "America/Sao_Paulo"
        if len(fuso) > 64 or not all(ch.isalnum() or ch in "/_+-" for ch in fuso):
            raise ErroApi(400, "fuso inválido")
        with ctx.tx() as ex:
            return 200, dp.execucao(ex, fuso)

    @r.rota("POST", "/api/lotes/proxima_etapa", exige=("supervisor",))
    def _proximas(req):
        ids = campo(req, "lotes", lambda v: [int(x) for x in v])
        if not ids:
            raise ErroApi(400, "escolha pelo menos uma folha")
        obs = campo(req, "observacao", str, padrao="")
        if not obs.strip():
            raise ErroApi(400, "escreva a observação: ela vai para o histórico de cada folha")
        return 200, abrir_proximas(ctx, uf_de(ctx.eu()), ids, obs)
