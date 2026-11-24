"""C1: funções da execução sobre o workspace (core/dados/local), com as regras da CCAR (D-94, D-102, D-106)."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from feixe.core.dados import ErroDados
from feixe.core.dados.local import cargas as lc
from feixe.core.dados.local import filas as lf

from tests.sync.conftest import USUARIO, carga

# As colunas que `cargas.minhas`/`proxima` da CCAR devolvem (core/dados/cargas.py, _CAMPOS).
CAMPOS_CCAR = {
    "id", "uuid", "id_lote_etapa", "id_lote", "folha_revisao", "tema", "etapa", "atividade", "geocodigo",
    "concluido", "concluido_em", "situacao_etapa", "xmin", "ymin", "xmax", "ymax",
}  # fmt: skip


def _outbox(ws):
    with ws.leitura() as ex:
        return ex.pendentes()


def test_minhas_no_formato_da_ccar(ws):
    with ws.leitura() as ex:
        itens = lc.minhas(ex)
        pendentes_11 = lc.minhas(ex, id_lote_etapa=11, concluido=False)
        uma = lc.uma(ex, 1001)
    assert [c["id"] for c in itens] == [1001, 1002, 1003, 3001]
    assert set(itens[0]) == CAMPOS_CCAR
    assert itens[0]["folha_revisao"] == "2534-1" and itens[0]["tema"] == "Hidrografia"
    assert itens[0]["etapa"] == "Aquisição" and itens[0]["atividade"] == "Aquisição BC100 - Hidrografia"
    assert itens[0]["concluido"] is False and itens[0]["situacao_etapa"] == "em_andamento"
    assert itens[0]["xmin"] == pytest.approx(-47.90) and itens[0]["ymax"] == pytest.approx(-15.75)
    assert [c["id"] for c in pendentes_11] == [1001, 1002, 1003]
    assert set(uma) == CAMPOS_CCAR | {"responsavel"} and uma["responsavel"] == USUARIO


def test_concluir_grava_hora_explicita_e_outbox(ws):
    hora = dt.datetime(2026, 11, 24, 13, 5, tzinfo=dt.timezone.utc)
    with ws.transacao(hora) as ex:
        r = lc.concluir(ex, 1001)
    assert r["carga"]["concluido"] is True and r["carga"]["concluido_em"] == hora
    assert r["progresso"] == {"id_lote_etapa": 11, "folha_revisao": "2534-1", "total": 3, "concluidas": 1}
    assert r["fila"] is None  # ainda tenho pendentes: a fila não anda
    (item,) = _outbox(ws)
    assert item["campos"] == {"concluido": True, "concluido_em": "2026-11-24T13:05:00.000Z"}
    assert item["hora"] == "2026-11-24T13:05:00.000000Z"


def test_concluir_de_novo_nao_faz_nada(ws):
    with ws.transacao() as ex:
        lc.concluir(ex, 1001)
    with ws.transacao() as ex:
        r = lc.concluir(ex, 1001)
    assert r["carga"]["concluido"] is True
    assert len(_outbox(ws)) == 1


def test_concluir_recusas(ws):
    with ws.transacao() as ex:
        with pytest.raises(ErroDados, match="encerrada pelo supervisor"):
            lc.concluir(ex, 3001)
        with pytest.raises(ErroDados, match="não está atribuída a você") as e:
            lc.concluir(ex, 1009)
        assert e.value.status == 403
        with pytest.raises(ErroDados, match="não encontrada") as e:
            lc.concluir(ex, 999)
        assert e.value.status == 404
    assert _outbox(ws) == []


def test_desfazer_ate_24_horas(ws):
    hora = dt.datetime(2026, 11, 24, 8, 0, tzinfo=dt.timezone.utc)
    with ws.transacao(hora) as ex:
        lc.concluir(ex, 1001)
        lc.concluir(ex, 1002)
    with ws.transacao(hora + dt.timedelta(hours=23)) as ex:
        r = lc.desfazer(ex, 1001)
    assert r["carga"]["concluido"] is False and r["carga"]["concluido_em"] is None
    assert r["progresso"]["concluidas"] == 1
    assert _outbox(ws)[-1]["campos"] == {"concluido": False, "concluido_em": None}
    with ws.transacao(hora + dt.timedelta(hours=24, minutes=1)) as ex:
        with pytest.raises(ErroDados, match="até 24 horas"):
            lc.desfazer(ex, 1002)
        with pytest.raises(ErroDados, match="não está concluída"):
            lc.desfazer(ex, 1003)
        with pytest.raises(ErroDados, match="não está atribuída a você"):
            lc.desfazer(ex, 1009)


def test_resumo_e_progresso(ws):
    hora = dt.datetime(2026, 11, 24, 8, 0, tzinfo=dt.timezone.utc)
    with ws.transacao(hora) as ex:
        lc.concluir(ex, 1001)
    with ws.leitura() as ex:
        r = lc.resumo(ex)
        assert lc.progresso(ex, 999) is None
    assert r["concluidas"] == 1 and r["desde"] == hora
    # 2534-1 aberta com 2 pendentes; 2536-1 encerrada mas com 1 pendente minha.
    assert r["pendentes"] == 3 and r["folhas_pendentes"] == 2
    assert [(p["folha_revisao"], p["total"], p["concluidas"]) for p in r["passagens"]] == [
        ("2534-1", 3, 1), ("2536-1", 1, 0)]  # fmt: skip
    assert set(r["passagens"][0]) == {"id_lote_etapa", "id_lote", "folha_revisao", "tema", "etapa", "situacao",
                                      "total", "concluidas", "ultima_conclusao"}  # fmt: skip
    assert r["passagens"][0]["ultima_conclusao"] == hora


def test_proxima_mesma_passagem_e_mais_perto(ws):
    with ws.leitura() as ex:
        # Referência 1001 (oeste): a mais perto na mesma passagem é a 1002; a 3001 está mais perto mas encerrada.
        assert lc.proxima(ex, 1001)["id"] == 1002
        assert lc.proxima(ex, 1001, excluir=[1002])["id"] == 1003
        assert lc.proxima(ex, 1003)["id"] == 1002
        assert lc.proxima(ex, 1001, id_lote=2) is None
        assert set(lc.proxima(ex, 1001)) == CAMPOS_CCAR
    with ws.transacao() as ex:
        lc.concluir(ex, 1003)
    with ws.leitura() as ex:
        # Sem referência: a última que concluí (1003) é a referência.
        assert lc.proxima(ex)["id"] == 1002


def test_proxima_prefere_a_mesma_passagem_mesmo_mais_longe(ws):
    with ws.transacao() as ex:
        # Uma carga minha em outra passagem aberta, colada na 1001.
        ex.gravar_remoto("carga_trabalho", {**carga(2003, 21, USUARIO, -47.91, -15.80)})
    with ws.leitura() as ex:
        assert lc.proxima(ex, 1001)["id"] == 1002
        assert lc.proxima(ex, 1001, excluir=[1002, 1003])["id"] == 2003


def test_pular_volta_depois_das_outras_da_folha(ws):
    puladas = {}
    with ws.leitura() as ex:
        r = lc.pular(ex, 1001, puladas)
        assert r["carga"]["id"] == 1002 and r["pulada"] == 1001 and puladas == {11: [1001]}
        assert r["progresso"]["folha_revisao"] == "2534-1"
        assert lc.proxima_sem_puladas(ex, 1002, puladas, (11, 1))["id"] == 1003
        lc.pular(ex, 1002, puladas)
        # Só a 1003 não foi pulada; depois dela, as puladas da folha voltam.
        assert lc.proxima_sem_puladas(ex, 1003, puladas, (11, 1))["id"] in (1001, 1002)
    assert _outbox(ws) == []  # pulo é só na memória (D-102)


def test_pular_a_unica_pendente_nao_pula(ws):
    with ws.transacao() as ex:
        lc.concluir(ex, 1001)
        lc.concluir(ex, 1002)
        ex.executar("UPDATE fila_folha SET responsavel = 'u_outro'")  # sem fila, para a 1003 ficar sozinha
    puladas = {}
    with ws.leitura() as ex:
        with pytest.raises(ErroDados, match="única carga pendente"):
            lc.pular(ex, 1003, puladas)
        assert puladas == {}  # como no plugin: sem não puladas na folha, as puladas dela voltam à rotação
        with pytest.raises(ErroDados, match="só dá para pular carga pendente"):
            lc.pular(ex, 1001, puladas)


def test_concluir_a_ultima_puxa_a_proxima_folha_da_fila(ws):
    hora = dt.datetime(2026, 11, 24, 15, 0, tzinfo=dt.timezone.utc)
    with ws.transacao(hora) as ex:
        lc.concluir(ex, 1001)
        lc.concluir(ex, 1002)
    antes = len(_outbox(ws))
    with ws.transacao(hora) as ex:
        r = lc.concluir(ex, 1003)
    assert r["fila"] == {"id": 501, "id_lote": 2, "id_lote_etapa": 21, "folha_revisao": "2535-0",
                         "tema": "Hidrografia", "atribuidas": 2}  # fmt: skip
    with ws.leitura() as ex:
        assert [c["id"] for c in lc.minhas(ex, id_lote_etapa=21)] == [2001, 2002]
        assert ex.um("SELECT situacao, iniciada_em, sujo FROM lote_etapa WHERE id = 21") == {
            "situacao": "em_andamento", "iniciada_em": "2026-11-24T15:00:00.000Z", "sujo": 1}  # fmt: skip
        f = ex.um("SELECT atribuida_em, atribuidas FROM fila_folha WHERE id = 501")
        assert f == {"atribuida_em": "2026-11-24T15:00:00.000Z", "atribuidas": 2}
        hist = ex.um("SELECT id, id_lote_etapa, acao, por, uf FROM lote_etapa_hist")
        assert hist == {"id": None, "id_lote_etapa": 21, "acao": "iniciar", "por": USUARIO, "uf": "DF"}
        # A próxima carga já vem da folha nova.
        assert lc.proxima(ex, 1003)["id_lote_etapa"] == 21
    itens = _outbox(ws)[antes:]
    assert [(i["tabela"], i["operacao"]) for i in itens] == [
        ("carga_trabalho", "update"),  # a conclusão da 1003
        ("carga_trabalho", "update"), ("carga_trabalho", "update"),  # 2001 e 2002 para mim
        ("lote_etapa", "update"), ("lote_etapa_hist", "insert"), ("fila_folha", "update"),
    ]  # fmt: skip
    assert itens[1]["campos"] == {"responsavel": USUARIO}
    assert {i["hora"] for i in itens} == {"2026-11-24T15:00:00.000000Z"}
    assert json.loads(json.dumps(itens[4]["campos"]))["observacao"] == "Iniciada ao distribuir as cargas"


def test_fila_vazia_ou_sem_cargas_a_atribuir_nao_atribui(ws):
    with ws.transacao() as ex:
        ex.executar("UPDATE carga_trabalho SET responsavel = 'u_outro' WHERE id_lote_etapa = 21")
        lc.concluir(ex, 1001)
        lc.concluir(ex, 1002)
        r = lc.concluir(ex, 1003)
        assert r["fila"] is None
        # O item continua na fila, para o supervisor ver e tirar.
        assert ex.um("SELECT atribuida_em FROM fila_folha WHERE id = 501")["atribuida_em"] is None
        ex.executar("DELETE FROM fila_folha")
        assert lf.puxar(ex, USUARIO) is None


def test_desfazer_nao_desatribui_a_folha_da_fila(ws):
    with ws.transacao() as ex:
        for i in (1001, 1002, 1003):
            lc.concluir(ex, i)
        lc.desfazer(ex, 1003)
        assert [c["id"] for c in lc.minhas(ex, id_lote_etapa=21)] == [2001, 2002]
