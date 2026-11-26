"""D3d: as leituras do painel sobre o workspace (core/dados/local/cq.py): minhas amostras por folha e elemento, as
ocorrências para dar ciência, a próxima amostra da folha e o "Ciente em todas desta folha". Cenário de
tests/sync/test_cq_execucao.py (plano 801 com n=3 e Ac=0, duas amostras minhas e uma de outro avaliador)."""

from __future__ import annotations

import datetime as dt

from feixe.core.dados.local import cq as lq

from tests.sync.conftest import USUARIO
from tests.sync.test_cq_execucao import cq  # noqa: F401 - fixture

UTC = dt.timezone.utc


def test_resumo_por_folha_e_elemento(ws, cq):  # noqa: F811
    with ws.leitura() as ex:
        r = lq.resumo(ex)
    assert [(x["id_lote_etapa"], x["aberta"]) for x in r] == [(12, True), (14, False)]  # aberta primeiro
    a = r[0]
    assert a["folha_revisao"] == "2534-1" and a["elemento"] == "Omissão" and a["plano"]["ac"] == 0
    # n=3 no plano, duas minhas: uma está com outro avaliador.
    assert (a["minhas"], a["total"], a["outras"], a["avaliadas"], a["pendentes"]) == (2, 3, 1, 0, 2)
    with ws.transacao(dt.datetime(2026, 11, 25, 9, 0, tzinfo=UTC)) as ex:
        lq.avaliar(ex, 9001, 0)
        lq.avaliar(ex, 9002, 1)
        lq.registrar(ex, -47.89, -15.79, 4001, "trecho")
    with ws.leitura() as ex:
        a = lq.resumo(ex)[0]
    assert (a["avaliadas"], a["nao_conformes"], a["pendentes"], a["ocorrencias"]) == (2, 1, 0, 1)
    assert a["ultima"] == dt.datetime(2026, 11, 25, 9, 0, tzinfo=UTC)


def test_para_ciencia_so_as_da_minha_carga(ws, cq):  # noqa: F811
    with ws.leitura() as ex:
        r = lq.para_ciencia(ex)
    # A 7001 aponta a minha 1001; as outras apontam a carga de outra pessoa.
    assert [o["uuid"] for o in r["pendentes"]] == [cq["autor"]] and r["cientes"] == []
    o = r["pendentes"][0]
    assert o["pode_ciente"] and o["responsavel"] == "u_aval" and o["elemento"] == "Omissão"
    assert "geocodigo_avaliada" in o
    # A ocorrência que eu mesmo registro (avaliador) não é "para ciência".
    with ws.transacao() as ex:
        lq.registrar(ex, -47.89, -15.79, 4001, "minha")
    with ws.leitura() as ex:
        assert [o["uuid"] for o in lq.para_ciencia(ex)["pendentes"]] == [cq["autor"]]


def test_ciente_em_todas_da_folha(ws, cq):  # noqa: F811
    with ws.transacao(dt.datetime(2026, 11, 25, 10, 0, tzinfo=UTC)) as ex:
        r = lq.ciente_da_folha(ex, 1)
    assert r == {"cientes": 1, "uuids": [cq["autor"]]}
    with ws.transacao() as ex:
        assert lq.ciente_da_folha(ex, 1)["cientes"] == 0  # de novo: nada
    with ws.leitura() as ex:
        ex.agora = dt.datetime(2026, 11, 26, tzinfo=UTC)
        r = lq.para_ciencia(ex)
    assert r["pendentes"] == [] and [o["ciente_por"] for o in r["cientes"]] == [USUARIO]


def test_proxima_amostra_da_folha_ignora_a_producao(ws, cq):  # noqa: F811
    with ws.leitura() as ex:
        r = lq.proxima_amostra(ex, 1)
        assert r["carga"]["id"] == 4001 and r["amostra"]["id"] == 9001  # a 5001 (produção, mesma folha) fica de fora
        assert lq.proxima_amostra(ex, 2) is None
    with ws.transacao() as ex:
        lq.avaliar(ex, 9001, 1)
        lq.avaliar(ex, 9002, 1)
    with ws.leitura() as ex:
        assert lq.proxima_amostra(ex, 1) is None
