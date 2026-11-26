"""D5: a correção de inspeção da execução sobre o workspace (core/dados/local/cq.py), sem rede: quem está com a folha
na correção vê todas as ocorrências da folha (todas as revisões, tratadas ou não), marca e desmarca tratada pela
outbox, e a carga da folha conclui no workspace com a última tratada (como o gatilho `t20_correcao`), sem outbox.

Cenário: o de tests/sync/conftest.py e, na folha 2534 (lote 1), as passagens de CQ das revisões 1 e 2 (já
concluídas) e a correção de inspeção aberta (passagem 15) com a carga da folha minha (6001, atividade manual).
Ocorrências da folha, registradas por `u_aval`: duas da revisão 1 (uma já tratada) e uma da revisão 2. Na 2535
(lote 2), uma ocorrência que não é da minha correção.
"""

from __future__ import annotations

import datetime as dt

import pytest
from feixe.core.dados import ErroDados
from feixe.core.dados.local import cargas as lc
from feixe.core.dados.local import cq as lq
from feixe.core.dados.local import grupos as lg
from feixe.sync import pull
from feixe.sync.geometria import wkb_ponto

from tests.sync.conftest import USUARIO, VERSAO, _aud, _u, carga

UTC = dt.timezone.utc


def _ocorrencia(id_, lote, le, tratado=False, x=-47.88):
    return {
        "id": id_, "uuid": _u(), "id_lote": lote, "id_lote_etapa": le, "id_carga_trabalho": None,
        "id_carga_avaliada": 1009, "uf": "DF", "elemento": "Omissão", "geom": wkb_ponto(x, -15.78),
        "anotacao": f"ocorrência {id_}", "responsavel": "u_aval", "tratado": tratado,
        "tratado_em": VERSAO if tratado else None, "tratado_por": "u_outro" if tratado else None, **_aud(),
    }  # fmt: skip


@pytest.fixture
def corr(ws):
    o = {}
    with ws.transacao() as ex:
        ex.gravar_remoto("atividade", {"id": 300, "cod_projeto": 5, "id_tema": 1, "fase": "correcao_inspecao",
                                       "nome": "Correção de inspeção BC100 - Hidrografia", "geracao": "manual",
                                       "ativo": True, "atualizado_em": VERSAO})  # fmt: skip
        ex.gravar_remoto("fase", {"codigo": "correcao_inspecao", "nome": "Correção de inspeção", "ordem": 4,
                                  "status_nacional": "EM_PRODUCAO"})  # fmt: skip
        for id_e, ordem, fase, nome in ((20, 2, "cq", "CQ"), (30, 3, "correcao_inspecao", "Correção de inspeção")):
            ex.gravar_remoto("fluxo_etapa", {"id": id_e, "id_fluxo": 1, "ordem": ordem, "fase": fase, "nome": nome,
                                             "atualizado_em": VERSAO})  # fmt: skip
        for id_le, etapa, inst, rev, sit in ((12, 20, 1, 1, "concluida"), (16, 20, 2, 2, "concluida"),
                                             (15, 30, 1, 2, "em_andamento")):  # fmt: skip
            ex.gravar_remoto("lote_etapa", {"id": id_le, "uuid": _u(), "id_lote": 1, "id_fluxo_etapa": etapa,
                                            "uf": "DF", "instancia": inst, "revisao": rev, "situacao": sit,
                                            "expor_ocorrencias": False, **_aud()})  # fmt: skip
        folha = carga(6001, 15, USUARIO, -47.95, -15.85)
        folha.update(id_atividade=300)
        ex.gravar_remoto("carga_trabalho", folha)
        for nome, linha in (
            ("r1", _ocorrencia(7101, 1, 12, x=-47.80)), ("r1_tratada", _ocorrencia(7102, 1, 12, tratado=True)),
            ("r2", _ocorrencia(7103, 1, 16, x=-47.90)), ("outra_folha", _ocorrencia(7104, 2, None)),
        ):  # fmt: skip
            ex.gravar_remoto("cq_inspecao", linha)
            o[nome] = linha["uuid"]
    return o


def _outbox(ws):
    with ws.leitura() as ex:
        return ex.pendentes()


def _folha(ws):
    with ws.leitura() as ex:
        return ex.um("SELECT concluido, concluido_em, sujo FROM carga_trabalho WHERE id = 6001")


def test_quem_esta_na_correcao_ve_todas_as_da_folha_de_todas_as_revisoes(ws, corr):
    with ws.leitura() as ex:
        vistas = lq.ocorrencias(ex, id_lote=1)
        assert {o["uuid"] for o in lq.ocorrencias(ex)} == {corr["r1"], corr["r1_tratada"], corr["r2"]}
    assert {o["uuid"] for o in vistas} == {corr["r1"], corr["r1_tratada"], corr["r2"]}
    assert all(o["pode_tratar"] and o["motivo"] == "correcao" for o in vistas)
    assert {o["revisao"] for o in vistas} == {1, 2}


def test_tratar_vai_pela_outbox_com_a_hora_e_aponta_a_proxima(ws, corr):
    hora = dt.datetime(2026, 11, 25, 14, 0, tzinfo=UTC)
    with ws.transacao(hora) as ex:
        r = lq.tratar(ex, corr["r2"])
    o = r["ocorrencia"]
    assert o["tratado"] is True and o["tratado_em"] == hora and o["tratado_por"] == USUARIO
    assert r["progresso"]["tratadas"] == 2 and r["progresso"]["total"] == 3 and r["progresso"]["pendentes"] == 1
    assert r["progresso"]["folha_revisao"] == "2534-2" and r["progresso"]["id_lote_etapa"] == 15
    assert r["proxima"]["uuid"] == corr["r1"] and r["fila"] is None
    (item,) = _outbox(ws)
    assert item["tabela"] == "cq_inspecao" and item["uuid"] == corr["r2"]
    assert item["campos"] == {"tratado": True, "tratado_em": "2026-11-25T14:00:00.000Z", "tratado_por": USUARIO}
    assert _folha(ws)["concluido"] == 0
    with ws.transacao() as ex:
        lq.tratar(ex, corr["r2"])  # de novo: nada muda
    assert len(_outbox(ws)) == 1


def test_a_ultima_conclui_a_carga_da_folha_e_desmarcar_reabre(ws, corr):
    hora = dt.datetime(2026, 11, 25, 15, 0, tzinfo=UTC)
    with ws.transacao(hora) as ex:
        lq.tratar(ex, corr["r2"])
        r = lq.tratar(ex, corr["r1"])
    assert r["progresso"]["pendentes"] == 0 and r["proxima"] is None
    f = _folha(ws)
    assert f["concluido"] == 1 and f["concluido_em"].startswith("2026-11-25T15:00:00")
    # A carga da folha quem conclui na CCAR é o gatilho: nada dela na outbox, e o pull não a mexe enquanto as
    # ocorrências não forem.
    assert {i["tabela"] for i in _outbox(ws)} == {"cq_inspecao"} and f["sujo"] == 0
    with ws.leitura() as ex:
        assert ex.um("SELECT uuid FROM carga_trabalho WHERE id = 6001")["uuid"] in pull._pendentes(ex, "carga_trabalho")
    with ws.transacao(hora + dt.timedelta(minutes=5)) as ex:
        r = lq.tratar(ex, corr["r1"], False)
    assert r["ocorrencia"]["tratado"] is False and r["ocorrencia"]["tratado_em"] is None
    assert r["progresso"]["pendentes"] == 1 and _folha(ws)["concluido"] == 0
    assert _outbox(ws)[-1]["campos"] == {"tratado": False, "tratado_em": None, "tratado_por": None}


def test_recusas_fora_da_correcao_e_a_carga_da_folha_nao_se_conclui_a_mao(ws, corr):
    with ws.transacao() as ex:
        with pytest.raises(ErroDados) as e:
            lq.tratar(ex, corr["outra_folha"])
        assert e.value.status == 403
        with pytest.raises(ErroDados) as e:
            lc.concluir(ex, 6001)
        assert "conclui sozinha" in e.value.mensagem
    with ws.transacao() as ex:
        ex.executar("UPDATE lote_etapa SET situacao = 'concluida' WHERE id = 15")
    with ws.transacao() as ex:
        with pytest.raises(ErroDados) as e:
            lq.tratar(ex, corr["r1"])  # o supervisor encerrou a correção: nem marcar, nem desmarcar
        assert e.value.status == 403
        assert lq.ocorrencias(ex, id_lote=1) == []  # fora do escopo da correção, e não é minha
    assert _outbox(ws) == []


def test_camadas_barra_e_painel_da_correcao(ws, corr):
    with ws.leitura() as ex:
        grupos = lg.execucao(ex)
        plano = lg.plano_execucao(grupos)
        pendentes = ex.todos(f"SELECT uuid FROM cq_inspecao WHERE {lg.filtro_correcao(False)}")
        tratadas = ex.todos(f"SELECT uuid FROM cq_inspecao WHERE {lg.filtro_correcao(True, [300])}")
        estado = lg.estado_cq(ex)
        fora = lg.fora_da_producao(ex)
        resumo = lq.correcao(ex)
        prox = lq.proxima_ocorrencia(ex)
        prox_carga = lc.proxima(ex, None, fora)
    (corr_plano,) = [p for p in plano if p["tipo"] == "correcao"]
    assert corr_plano == {"tipo": "correcao", "rotulo": "Correção · Hidrografia", "atividades": [300], "cargas": False}
    assert {r["uuid"] for r in pendentes} == {corr["r1"], corr["r2"]}
    assert [r["uuid"] for r in tratadas] == [corr["r1_tratada"]]
    assert estado["correcao"] == 3 and estado["correcao_pendentes"] == 2
    assert 6001 in fora and prox_carga["id"] != 6001  # Próxima carga não vai para a folha inteira
    (f,) = resumo
    assert (f["folha_revisao"], f["total"], f["tratadas"], f["so_folha"]) == ("2534-2", 3, 1, True)
    assert [o["tratado"] for o in f["ocorrencias"]] == [False, False, True]  # por tratar primeiro
    assert prox["uuid"] in (corr["r1"], corr["r2"])
