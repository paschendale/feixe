"""D3a: o CQ da execução sobre o workspace (core/dados/local/cq.py), sem rede: avaliar a amostra (a carga de CQ conclui
como pelo gatilho do banco), registrar, editar e apagar ocorrência, ciência do operador autor e a visibilidade do D-66.

Cenário: o de tests/sync/conftest.py e, na folha 2534 (lote 1), a passagem de CQ 12 (revisão 1, em andamento) com o
plano 801 e três cargas de CQ (4001 e 4002 minhas, 4003 de outro avaliador), a revisão seguinte (passagem 13, revisão
2) com uma carga minha, e na 2536 uma passagem de CQ já concluída com uma amostra minha (4009). Ocorrências vindas da
CCAR, registradas por `u_aval`: uma aponta a minha carga 1001 (sou o autor), outra a 1009 (de `u_outro`), outra
igual já tratada.
"""

from __future__ import annotations

import datetime as dt

import pytest
from feixe.core.dados import ErroDados
from feixe.core.dados.local import cq as lq
from feixe.sync import pull
from feixe.sync.geometria import wkb_ponto

from tests.sync.conftest import USUARIO, VERSAO, _aud, _u, carga

UTC = dt.timezone.utc


def _cq(id_, le, plano, resp, x):
    c = carga(id_, le, resp, x, -15.80)
    c.update(id_atividade=200, id_cq_plano=plano)
    return c


def _ocorrencia(id_, avaliada, tratado=False, x=-47.88):
    return {
        "id": id_, "uuid": _u(), "id_lote": 1, "id_lote_etapa": 12, "id_carga_trabalho": 4003,
        "id_carga_avaliada": avaliada, "uf": "DF", "elemento": "Omissão", "geom": wkb_ponto(x, -15.78),
        "anotacao": f"ocorrência {id_}", "responsavel": "u_aval", "tratado": tratado, **_aud(),
    }  # fmt: skip


@pytest.fixture
def cq(ws):
    o = {}
    with ws.transacao() as ex:
        ex.gravar_remoto("atividade", {"id": 200, "cod_projeto": 5, "id_tema": 1, "fase": "cq",
                                       "nome": "CQ Hidrografia - Omissão", "geracao": "amostra_area",
                                       "elemento": "Omissão", "ativo": True, "atualizado_em": VERSAO})  # fmt: skip
        ex.gravar_remoto("fluxo_etapa", {"id": 20, "id_fluxo": 1, "ordem": 2, "fase": "cq", "nome": "CQ",
                                         "atualizado_em": VERSAO})  # fmt: skip
        for id_le, id_lote, etapa, inst, rev, sit in (
            (12, 1, 20, 1, 1, "em_andamento"), (13, 1, 10, 2, 2, "em_andamento"), (14, 3, 20, 1, 1, "concluida"),
        ):  # fmt: skip
            ex.gravar_remoto("lote_etapa", {"id": id_le, "uuid": _u(), "id_lote": id_lote, "id_fluxo_etapa": etapa,
                                            "uf": "DF", "instancia": inst, "revisao": rev, "situacao": sit,
                                            "expor_ocorrencias": False, **_aud()})  # fmt: skip
        for id_p, le in ((801, 12), (802, 14)):
            ex.gravar_remoto("cq_plano", {"id": id_p, "uuid": _u(), "id_lote_etapa": le, "id_atividade": 200,
                                          "uf": "DF", "nivel_inspecao": "II", "letra_codigo": "B", "tamanho_lote_n": 9,
                                          "tamanho_amostra_n": 3, "numero_aceitacao_ac": 0, "lqa": 4.0,
                                          "resultado": "pendente", **_aud()})  # fmt: skip
        for c in (
            _cq(4001, 12, 801, USUARIO, -47.90), _cq(4002, 12, 801, USUARIO, -47.70),
            _cq(4003, 12, 801, "u_aval", -47.88), _cq(4009, 14, 802, USUARIO, -47.89),
            carga(5001, 13, USUARIO, -47.95, -15.80),
        ):  # fmt: skip
            ex.gravar_remoto("carga_trabalho", c)
        for id_a, plano, c in ((9001, 801, 4001), (9002, 801, 4002), (9003, 801, 4003), (9009, 802, 4009)):
            ex.gravar_remoto("cq_amostra", {"id": id_a, "uuid": _u(), "id_cq_plano": plano, "id_carga_trabalho": c,
                                            "uf": "DF", **_aud()})  # fmt: skip
        for nome, linha in (("autor", _ocorrencia(7001, 1001)), ("outro", _ocorrencia(7002, 1009)),
                            ("tratada", _ocorrencia(7003, 1009, tratado=True))):  # fmt: skip
            ex.gravar_remoto("cq_inspecao", linha)
            o[nome] = linha["uuid"]
    return o


def _outbox(ws):
    with ws.leitura() as ex:
        return ex.pendentes()


def _carga(ws, id_):
    with ws.leitura() as ex:
        return ex.um("SELECT concluido, concluido_em, versao_base, sujo FROM carga_trabalho WHERE id = ?", (id_,))


# --- avaliar ---------------------------------------------------------------------------------------------------------


def test_minhas_amostras_com_plano_elemento_e_folha(ws, cq):
    with ws.leitura() as ex:
        itens = lq.amostras(ex)
        pendentes_12 = lq.amostras(ex, id_lote_etapa=12, pendente=True)
    assert [a["id"] for a in itens] == [9001, 9002, 9009]  # a 9003 é de outro avaliador
    a = itens[0]
    assert a["folha_revisao"] == "2534-1" and a["elemento"] == "Omissão" and a["etapa"] == "CQ"
    assert a["plano"] == {"id": 801, "nivel": "II", "letra": "B", "N": 9, "n": 3, "ac": 0, "lqa": 4.0,
                          "resultado": "pendente"}  # fmt: skip
    assert a["avaliada"] is False and a["concluido"] is False and a["ocorrencias"] == 0
    assert [x["id"] for x in pendentes_12] == [9001, 9002]


def test_avaliar_conclui_a_carga_de_cq_e_aponta_a_proxima(ws, cq):
    hora = dt.datetime(2026, 11, 25, 9, 30, tzinfo=UTC)
    antes = _carga(ws, 4001)
    with ws.transacao(hora) as ex:
        r = lq.avaliar(ex, 9001, 0, " omissão de trecho ")
    assert r["amostra"]["status"] == 0 and r["amostra"]["observacao"] == "omissão de trecho"
    assert r["amostra"]["avaliado_em"] == hora and r["amostra"]["avaliado_por"] == USUARIO
    assert r["carga"]["concluido"] is True and r["carga"]["concluido_em"] == hora
    assert r["progresso"] == {"id_lote_etapa": 12, "folha_revisao": "2534-1", "total": 2, "concluidas": 1}
    # A próxima amostra: a outra carga de CQ pendente (as de produção ficam de fora).
    assert r["proxima"]["carga"]["id"] == 4002 and r["proxima"]["amostra"]["id"] == 9002
    (item,) = _outbox(ws)  # só a amostra: a carga de CQ quem conclui na CCAR é o gatilho
    assert item["tabela"] == "cq_amostra"
    assert item["campos"] == {"status": 0, "avaliado_em": "2026-11-25T09:30:00.000Z", "avaliado_por": USUARIO,
                              "observacao": "omissão de trecho"}  # fmt: skip
    depois = _carga(ws, 4001)
    assert depois["versao_base"] == antes["versao_base"] and depois["sujo"] == 0
    with ws.transacao() as ex:
        r = lq.avaliar(ex, 9002, 1)
    assert r["proxima"] is None  # acabaram as amostras pendentes


def test_trocar_a_avaliacao_enquanto_a_passagem_esta_aberta(ws, cq):
    h1 = dt.datetime(2026, 11, 25, 9, 0, tzinfo=UTC)
    with ws.transacao(h1) as ex:
        lq.avaliar(ex, 9001, 1)
    with ws.transacao(h1 + dt.timedelta(minutes=5)) as ex:
        r = lq.avaliar(ex, 9001, 1, "ok")  # só a observação: a hora da avaliação fica
    assert r["amostra"]["avaliado_em"] == h1
    with ws.transacao(h1 + dt.timedelta(minutes=10)) as ex:
        r = lq.avaliar(ex, 9001, 0)  # trocou o status: nova hora
    assert r["amostra"]["status"] == 0 and r["amostra"]["avaliado_em"] == h1 + dt.timedelta(minutes=10)
    assert r["carga"]["concluido_em"] == h1  # a carga continua concluída da primeira vez
    with ws.transacao() as ex:
        lq.avaliar(ex, 9001, 0)  # nada mudou: nada na outbox
    assert [set(i["campos"]) for i in _outbox(ws)] == [
        {"status", "avaliado_em", "avaliado_por"}, {"observacao"}, {"status", "avaliado_em", "avaliado_por"},
    ]  # fmt: skip


def test_avaliar_recusas(ws, cq):
    with ws.transacao() as ex:
        with pytest.raises(ErroDados, match="1 .conforme. ou 0") as e:
            lq.avaliar(ex, 9001, 2)
        assert e.value.status == 400
        with pytest.raises(ErroDados, match="não é de uma carga sua") as e:
            lq.avaliar(ex, 9003, 1)
        assert e.value.status == 403
        with pytest.raises(ErroDados, match="encerrada pelo supervisor"):
            lq.avaliar(ex, 9009, 1)
        with pytest.raises(ErroDados, match="não encontrada") as e:
            lq.avaliar(ex, 1, 1)
        assert e.value.status == 404
    assert _outbox(ws) == []


def test_avaliar_a_ultima_pendente_anda_a_fila(ws, cq):
    """Sem nenhuma outra carga pendente, avaliar a última amostra conclui a carga e a fila passa a próxima folha."""
    with ws.transacao() as ex:
        ex.executar("UPDATE carga_trabalho SET concluido = 1 WHERE responsavel = ? AND id_cq_plano IS NULL", (USUARIO,))
        lq.avaliar(ex, 9001, 1)
        r = lq.avaliar(ex, 9002, 1)
    assert r["fila"]["id_lote_etapa"] == 21 and r["fila"]["atribuidas"] == 2


def test_pull_nao_desfaz_a_carga_concluida_pela_amostra_antes_do_push(ws, cq):
    with ws.transacao() as ex:
        lq.avaliar(ex, 9001, 1)
    with ws.leitura() as ex:
        uuid_carga = ex.um("SELECT uuid FROM carga_trabalho WHERE id = 4001")["uuid"]
        assert uuid_carga in pull._pendentes(ex, "carga_trabalho")


# --- ocorrências -----------------------------------------------------------------------------------------------------


def test_registrar_ocorrencia_offline(ws, cq):
    hora = dt.datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
    with ws.transacao(hora) as ex:
        r = lq.registrar(ex, -47.89, -15.79, 4001, "  falta o trecho  ")
    o = r["ocorrencia"]
    assert o["id"] is None and o["enviada"] is False and o["minha"] and o["pode_editar"] and o["motivo"] == "registrada"
    assert (o["x"], o["y"]) == (pytest.approx(-47.89), pytest.approx(-15.79))
    assert (o["id_lote"], o["id_lote_etapa"], o["id_carga_trabalho"]) == (1, 12, 4001)
    assert o["elemento"] == "Omissão" and o["anotacao"] == "falta o trecho" and o["folha_revisao"] == "2534-1"
    assert r["amostra"]["id"] == 9001 and r["amostra"]["ocorrencias"] == 1
    (item,) = _outbox(ws)
    assert item["operacao"] == "insert" and item["tabela"] == "cq_inspecao" and item["uuid"] == o["uuid"]
    c = item["campos"]
    assert c["responsavel"] == USUARIO and c["id_lote_etapa"] == 12 and c["tratado"] is False
    assert bytes.fromhex(c["geom"]) == wkb_ponto(-47.89, -15.79)
    assert "id_carga_avaliada" not in c  # quem deriva é o banco, no INSERT


def test_registrar_recusas(ws, cq):
    with ws.transacao() as ex:
        with pytest.raises(ErroDados, match="carga de CQ") as e:
            lq.registrar(ex, -47.9, -15.8, 1001)  # carga de produção
        assert e.value.status == 400
        with pytest.raises(ErroDados, match="não está atribuída a você"):
            lq.registrar(ex, -47.9, -15.8, 4003)
        with pytest.raises(ErroDados, match="encerrada"):
            lq.registrar(ex, -47.9, -15.8, 4009)
        with pytest.raises(ErroDados, match="ponto inválido"):
            lq.registrar(ex, "x", -15.8, 4001)
        with pytest.raises(ErroDados, match="ponto inválido"):
            lq.registrar(ex, -15.8, -247.9, 4001)
    assert _outbox(ws) == []


def test_editar_e_apagar_a_propria(ws, cq):
    with ws.transacao() as ex:
        u = lq.registrar(ex, -47.89, -15.79, 4001, "a")["ocorrencia"]["uuid"]
    with ws.transacao() as ex:
        r = lq.editar(ex, u, "b", -47.885, -15.785)
        assert r["ocorrencia"]["anotacao"] == "b" and r["ocorrencia"]["x"] == pytest.approx(-47.885)
        assert lq.editar(ex, u, "b")["ocorrencia"]["anotacao"] == "b"  # sem mudança, sem item
        with pytest.raises(ErroDados, match="outra pessoa") as e:
            lq.editar(ex, cq["autor"], "minha versão")
        assert e.value.status == 403
        with pytest.raises(ErroDados, match="outra pessoa"):
            lq.apagar(ex, cq["autor"])
    with ws.transacao() as ex:
        lq.apagar(ex, u)
        assert lq.ocorrencia(ex, u) is None
    ops = [(i["operacao"], sorted(i["campos"])) for i in _outbox(ws)]
    assert ops[1] == ("update", ["anotacao", "geom"]) and ops[2] == ("delete", ["anotacao", "elemento"])
    assert ops[0][0] == "insert" and len(ops) == 3


def test_ocorrencia_nao_muda_com_a_passagem_de_cq_encerrada(ws, cq):
    with ws.transacao() as ex:
        u = lq.registrar(ex, -47.89, -15.79, 4001)["ocorrencia"]["uuid"]
        ex.executar("UPDATE lote_etapa SET situacao = 'concluida' WHERE id = 12")
        with pytest.raises(ErroDados, match="encerrada"):
            lq.editar(ex, u, "tarde")
        with pytest.raises(ErroDados, match="encerrada"):
            lq.apagar(ex, u)
        assert lq.ocorrencia(ex, u)["pode_editar"] is False


def test_ciente_do_apm_autor(ws, cq):
    hora = dt.datetime(2026, 11, 26, 8, 0, tzinfo=UTC)
    with ws.leitura() as ex:
        antes = lq.ocorrencia(ex, cq["autor"])
    assert antes["sou_autor"] and antes["pode_ciente"] and antes["motivo"] == "minha_carga" and not antes["minha"]
    with ws.transacao(hora) as ex:
        r = lq.ciente(ex, cq["autor"])
    assert r["ocorrencia"]["ciente_em"] == hora and r["ocorrencia"]["ciente_por"] == USUARIO
    assert r["ocorrencia"]["pode_ciente"] is False
    with ws.transacao() as ex:
        lq.ciente(ex, cq["autor"])  # de novo: nada
        with pytest.raises(ErroDados, match="só quem fez a carga") as e:
            lq.ciente(ex, cq["outro"])
        assert e.value.status == 403
    (item,) = _outbox(ws)
    assert item["campos"] == {"ciente_em": "2026-11-26T08:00:00.000Z", "ciente_por": USUARIO}


def test_visibilidade_do_d66(ws, cq):
    """A revisão seguinte é às cegas: com carga na passagem 13 (revisão 2) eu não vejo a ocorrência da 1009; com
    "incluir correções a serem feitas" (expor_ocorrencias) na 13, vejo as não tratadas como lista de correção."""
    with ws.transacao() as ex:
        mia = lq.registrar(ex, -47.89, -15.79, 4001)["ocorrencia"]["uuid"]
    with ws.leitura() as ex:
        vistas = {o["uuid"]: o["motivo"] for o in lq.ocorrencias(ex, id_lote=1)}
        assert lq.ocorrencia(ex, cq["outro"]) is None
        assert [o["uuid"] for o in lq.ocorrencias(ex, id_lote_etapa=99)] == []
    assert vistas == {cq["autor"]: "minha_carga", mia: "registrada"}
    with ws.transacao() as ex:
        ex.executar("UPDATE lote_etapa SET expor_ocorrencias = 1 WHERE id = 13")
    with ws.leitura() as ex:
        vistas = {o["uuid"]: o["motivo"] for o in lq.ocorrencias(ex, id_lote=1)}
    assert vistas == {cq["autor"]: "minha_carga", mia: "registrada", cq["outro"]: "correcao"}  # a tratada, não
    with ws.transacao() as ex:
        ex.executar("UPDATE lote_etapa SET situacao = 'concluida' WHERE id = 13")
    with ws.leitura() as ex:
        assert cq["outro"] not in {o["uuid"] for o in lq.ocorrencias(ex, id_lote=1)}
