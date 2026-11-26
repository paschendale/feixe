"""Painel no navegador (D-103): Início por papel, "Esperando você", a próxima etapa em várias folhas (D-109) e a
decisão sobre o resultado do CQ (D4)."""

from __future__ import annotations

import contextlib
from typing import Dict, Iterable, List

from ...core.dados import ErroDados
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
    elemento (D3d), as ocorrências das minhas cargas para dar ciência (D-66) e as minhas folhas na correção de
    inspeção, com as ocorrências a tratar (D5)."""
    r = lc.execucao(ex, tz)
    r["cq"] = lq.resumo(ex)
    r["ciencia"] = lq.para_ciencia(ex)
    r["correcao"] = lq.correcao(ex)
    return r


def _com_nomes(ctx, r: Dict) -> Dict:
    ciencia = r["ciencia"]
    todas = ciencia["pendentes"] + ciencia["cientes"] + [o for f in r.get("correcao") or [] for o in f["ocorrencias"]]
    nomes = _nomes(ctx, [o["responsavel"] for o in todas])
    for o in todas:
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


def decidir_cq(ctx, uf: str, ids: List[int], decisao: str, observacao: str, previa: bool, forcar=False, expor=False):
    """Aprovar ou Nova revisão no CQ de várias folhas (D4): na prévia, o que acontece em cada uma; sem prévia, cada
    folha na sua transação (uma recusa não desfaz as outras), e as cargas da etapa aberta saem em seguida."""
    if previa:
        with ctx.tx() as ex:
            return df.previa_cq(ex, uf, ids, decisao)
    if decisao not in df.DECISOES_CQ:
        raise ErroApi(400, "decisão do CQ: aprovar ou nova_revisao")
    abertas, decididas, erros = [], [], []
    for i in ids:
        try:
            with ctx.tx() as ex:
                d = df.decidir_cq(ex, uf, i, decisao, observacao, forcar, expor)
        except ErroDados as e:
            if e.status == 400:
                raise ErroApi(400, e.mensagem) from None
            erros.append({"id_lote": i, "erro": e.mensagem})
            continue
        decididas.append({"id_lote": i, "folha_revisao": d["folha_revisao"], "resultado": d["resultado"]})
        if d["id_lote_etapa_nova"]:
            abertas.append({"id_lote": i, "id_lote_etapa": d["id_lote_etapa_nova"], "etapa": d["proxima"]})
    if decididas:
        ctx.publicar("lote", {"acao": "cq_" + decisao, "ids": [d["id_lote"] for d in decididas]})
    return _abertas(ctx, uf, {"decididas": decididas, "abertas": abertas, "erros": erros})


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
                         "correcao": [], "preparando": True}  # fmt: skip
        with ctx.leitura() as ex:
            r = execucao(ctx, ex, tz)
        # Os nomes fora da leitura do workspace: a consulta à CCAR (quando falta um nome) não segura o GeoPackage.
        return 200, _com_nomes(ctx, r)

    @r.rota("POST", "/api/lotes/cq_decisao", exige=("supervisor",))
    def _cq_decisao(req):
        ids = campo(req, "lotes", lambda v: [int(x) for x in v])
        if not ids:
            raise ErroApi(400, "escolha pelo menos um lote")
        return 200, decidir_cq(
            ctx, uf_de(ctx.eu()), ids, campo(req, "decisao", str), campo(req, "observacao", str, padrao=""),
            campo(req, "previa", bool, padrao=True), campo(req, "forcar", bool, padrao=False),
            campo(req, "expor_ocorrencias", bool, padrao=False),
        )  # fmt: skip

    @r.rota("POST", "/api/lotes/encerrar", exige=("supervisor",))
    def _encerrar(req):
        # Fim do fluxo (D-153): a folha passa a CONCLUIDA para a CCAR, por decisão do supervisor, em lote, com prévia.
        # `antecipar` (D-161) encerra antes do fim do fluxo, pulando as etapas que faltam; exige o motivo.
        ids = campo(req, "lotes", lambda v: [int(x) for x in v])
        if not ids:
            raise ErroApi(400, "escolha pelo menos um lote")
        previa = campo(req, "previa", bool, padrao=True)
        with ctx.tx() as ex:
            r = df.encerrar(ex, uf_de(ctx.eu()), ids, campo(req, "observacao", str, padrao=""), previa,
                            campo(req, "antecipar", bool, padrao=False))  # fmt: skip
        if not previa and r["encerradas"]:
            ctx.publicar("lote", {"acao": "encerrar", "ids": [i["id_lote"] for i in r["encerradas"]]})
        return 200, r

    @r.rota("POST", "/api/lotes/avancar", exige=("supervisor",))
    def _avancar(req):
        ids = campo(req, "lotes", lambda v: [int(x) for x in v])
        if not ids:
            raise ErroApi(400, "escolha pelo menos um lote")
        previa = campo(req, "previa", bool, padrao=True)
        return 200, avancar(ctx, uf_de(ctx.eu()), ids, campo(req, "observacao", str, padrao=""), previa)
