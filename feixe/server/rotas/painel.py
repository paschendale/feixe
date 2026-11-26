"""Painel no navegador (D-103): Início por papel, "Esperando você" e a próxima etapa em várias folhas (D-109)."""

from __future__ import annotations

import contextlib
from typing import Dict, Iterable, List

from ...core.dados import fluxos as df
from ...core.dados import painel as dp
from ...core.dados.local import cargas as lc
from ...core.dados.local import cq as lq
from ..api import ErroApi, campo, fuso_de
from .cargas import EXECUTORES, preparar
from .lotes import uf_de

# Nome de quem avaliou (Para ciência): o workspace não tem os nomes do SGBC. Com a CCAR respondendo, uma consulta só
# pelas contas que faltam, guardadas na memória do plugin; sem ela, fica a conta (a tela mostra o que tem).
_NOMES: Dict[str, str] = {}


def _nomes(ctx, contas: Iterable[str]) -> Dict[str, str]:
    faltam = sorted({c for c in contas if c and c not in _NOMES})
    if faltam:
        with contextlib.suppress(Exception):
            with ctx.tx() as ex:
                achados = dp.nomes(ex, faltam)
            # Conta sem cadastro fica com ela mesma: não se pergunta de novo a cada leitura.
            _NOMES.update({c: achados.get(c, c) for c in faltam})
    return {c: _NOMES.get(c, c) for c in contas if c}


def execucao(ctx, ex, tz) -> Dict:
    """Início e Execução de quem executa, do workspace (C3): conclusões por dia, minhas amostras de CQ por folha e
    elemento (D3d) e as ocorrências das minhas cargas para dar ciência (D-66)."""
    r = lc.execucao(ex, tz)
    r["cq"] = lq.resumo(ex)
    r["ciencia"] = lq.para_ciencia(ex)
    return r


def _com_nomes(ctx, r: Dict) -> Dict:
    ciencia = r["ciencia"]
    nomes = _nomes(ctx, [o["responsavel"] for o in ciencia["pendentes"] + ciencia["cientes"]])
    for o in ciencia["pendentes"] + ciencia["cientes"]:
        o["avaliador"] = nomes.get(o["responsavel"], o["responsavel"])
    return r


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
            return 200, {"por_dia": [], "cq": [], "ciencia": {"pendentes": [], "cientes": [], "dias": 30},
                         "preparando": True}  # fmt: skip
        with ctx.leitura() as ex:
            r = execucao(ctx, ex, tz)
        # Os nomes fora da leitura do workspace: a consulta à CCAR (quando falta um nome) não segura o GeoPackage.
        return 200, _com_nomes(ctx, r)

    @r.rota("POST", "/api/lotes/avancar", exige=("supervisor",))
    def _avancar(req):
        ids = campo(req, "lotes", lambda v: [int(x) for x in v])
        if not ids:
            raise ErroApi(400, "escolha pelo menos uma folha")
        previa = campo(req, "previa", bool, padrao=True)
        return 200, avancar(ctx, uf_de(ctx.eu()), ids, campo(req, "observacao", str, padrao=""), previa)
