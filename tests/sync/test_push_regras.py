"""C3: as partes puras do push (sem banco): relógio, junção da outbox, decisão da última escrita e regras da carga."""

from __future__ import annotations

import datetime as dt

from feixe.core.dados.local import cargas as lc
from feixe.sync import push

from tests.sync.conftest import USUARIO

UTC = dt.timezone.utc
T = dt.datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def test_desvio_e_correcao_do_relogio():
    # Estação 2 min adiantada: leu 12:02:00 antes e 12:02:00.2 depois de o servidor dizer 12:00:00.1.
    t0, t1 = T + dt.timedelta(minutes=2), T + dt.timedelta(minutes=2, milliseconds=200)
    d = push.estimar_desvio(t0, T + dt.timedelta(milliseconds=100), t1)
    assert d == dt.timedelta(minutes=-2)
    assert push.corrigir(T + dt.timedelta(minutes=2), d) == T
    # Nunca depois da hora do servidor: ação "no futuro" fica na hora do push.
    assert push.corrigir(T + dt.timedelta(hours=1), dt.timedelta(0), teto=T) == T


def test_decidir():
    assert push.decidir("v1", "v1", T, T + dt.timedelta(hours=1)) == "aplicado"
    assert push.decidir("v1", "v2", T + dt.timedelta(seconds=1), T) == "conflito_vencido"
    assert push.decidir("v1", "v2", T, T + dt.timedelta(seconds=1)) == "conflito_perdido"
    assert push.decidir(None, "v2", T, T) == "conflito_perdido"  # empate fica com o servidor


def _item(id_, tabela, uuid, campos, acao, op="update", base="v0"):
    hora = f"2026-11-24T12:00:0{id_}.000000Z"
    return {"id": id_, "chave": f"k{id_}", "acao": acao, "tabela": tabela, "uuid": uuid, "operacao": op,
            "campos": campos, "hora": hora, "versao_base": base, "tentativas": 0}  # fmt: skip


def test_juntar_concluir_e_desfazer_seguidos():
    itens = [
        _item(1, "carga_trabalho", "a", {"concluido": True, "concluido_em": "x"}, "A1"),
        _item(2, "carga_trabalho", "a", {"concluido": False, "concluido_em": None}, "A2", base="v0"),
        _item(3, "carga_trabalho", "b", {"concluido": True}, "A3"),
        _item(4, "carga_trabalho", "a", {"concluido": True}, "A4"),
    ]
    passos = push.juntar(itens)
    assert [p[0] for p in passos] == ["envio", "envio", "envio"]
    g = passos[0][1]
    assert g["campos"] == {"concluido": False, "concluido_em": None} and [i["id"] for i in g["itens"]] == [1, 2]
    assert g["hora"] == itens[1]["hora"] and g["versao_base"] == "v0"
    assert [j["chave"] for j in g["juntados"]] == ["k1", "k2"]
    # O item 4 é da mesma linha, mas não é seguido (a carga b está no meio): não se junta.
    assert passos[2][1]["itens"][0]["id"] == 4 and passos[2][1]["juntados"] is None


def test_puxar_da_fila_vira_unidade_e_o_concluir_fica_fora():
    itens = [
        _item(1, "carga_trabalho", "a", {"concluido": True, "concluido_em": "x"}, "A1"),
        _item(2, "carga_trabalho", "b1", {"responsavel": USUARIO}, "A1"),
        _item(3, "carga_trabalho", "b2", {"responsavel": USUARIO}, "A1"),
        _item(4, "lote_etapa", "le", {"situacao": "em_andamento", "iniciada_em": "x"}, "A1"),
        _item(5, "lote_etapa_hist", "h", {"acao": "iniciar"}, "A1", op="insert", base=None),
        _item(6, "fila_folha", "f", {"atribuida_em": "x", "atribuidas": 2}, "A1"),
    ]
    passos = push.juntar(itens)
    assert [p[0] for p in passos] == ["envio", "unidade"]
    assert [g["itens"][0]["id"] for g in passos[1][1]] == [2, 3, 4, 5, 6]
    # Sem o item da fila, mudar o responsável é um envio comum (não há puxar).
    assert [p[0] for p in push.juntar(itens[1:3])] == ["envio", "envio"]


class _Falso:
    """O mínimo de `_Push` que as regras da carga usam."""

    def __init__(self, situacao="em_andamento"):
        self.p = push._Push(None, None, USUARIO, "DF", dt.timedelta(0), T)
        self.p.etapas = {11: {"situacao": situacao, "cod_projeto": 5, "folha": "2534-1"}}

    def regras(self, srv, valores, hora=T):
        return self.p.regras_carga({}, srv, valores, hora)


def test_regras_da_carga_no_servidor():
    minha = {"responsavel": USUARIO, "id_lote_etapa": 11, "concluido": False, "concluido_em": None}
    assert _Falso().regras(minha, {"concluido": True}) is None
    assert "não está mais atribuída" in _Falso().regras({**minha, "responsavel": "outro"}, {"concluido": True})
    assert "encerrada" in _Falso("concluida").regras(minha, {"concluido": True})
    feita = {**minha, "concluido": True, "concluido_em": T - dt.timedelta(hours=23)}
    assert _Falso().regras(feita, {"concluido": False}) is None
    assert f"{lc.JANELA_DESFAZER_HORAS} horas" in _Falso().regras(
        feita, {"concluido": False}, T + dt.timedelta(hours=2)
    )
    # Mudar outra coisa numa etapa encerrada não esbarra na regra do concluir.
    assert _Falso("concluida").regras(feita, {"concluido": True}) is None


# --- CQ (D3a) --------------------------------------------------------------------------------------------------------


def _cq(situacao="em_andamento"):
    p = push._Push(None, None, USUARIO, "DF", dt.timedelta(0), T)
    p.etapas = {12: {"situacao": situacao, "cod_projeto": 5, "folha": "2534-1"}}
    p.cargas_cq = {
        4001: {"id": 4001, "uuid": "c1", "responsavel": USUARIO, "id_lote_etapa": 12, "id_cq_plano": 801},
        4003: {"id": 4003, "uuid": "c3", "responsavel": "u_aval", "id_lote_etapa": 12, "id_cq_plano": 801},
        1001: {"id": 1001, "uuid": "p1", "responsavel": USUARIO, "id_lote_etapa": 11, "id_cq_plano": None},
        1009: {"id": 1009, "uuid": "p9", "responsavel": "u_outro", "id_lote_etapa": 11, "id_cq_plano": None},
    }
    return p


def test_regras_da_amostra_no_servidor():
    assert _cq().regras_amostra({"id_carga_trabalho": 4001}) is None
    assert "não é mais de uma carga sua" in _cq().regras_amostra({"id_carga_trabalho": 4003})
    assert "não existe mais" in _cq().regras_amostra({"id_carga_trabalho": 4999})
    assert "encerrada" in _cq("concluida").regras_amostra({"id_carga_trabalho": 4001})


def test_regras_da_ocorrencia_nova_no_servidor():
    nova = {"id_carga_trabalho": 4001, "responsavel": USUARIO}
    assert _cq().regras_ocorrencia_nova(nova) is None
    assert "outra pessoa" in _cq().regras_ocorrencia_nova({**nova, "responsavel": "u_aval"})
    assert "não está mais atribuída" in _cq().regras_ocorrencia_nova({**nova, "id_carga_trabalho": 4003})
    assert "não existe mais" in _cq().regras_ocorrencia_nova({**nova, "id_carga_trabalho": 1001})  # não é de CQ
    assert "encerrada" in _cq("concluida").regras_ocorrencia_nova(nova)


def test_regras_de_editar_e_dar_ciencia_no_servidor():
    minha = {"responsavel": USUARIO, "id_lote_etapa": 12, "id_carga_avaliada": 1009}
    dele = {"responsavel": "u_aval", "id_lote_etapa": 12, "id_carga_avaliada": 1001}
    assert _cq().regras_ocorrencia(minha, ["anotacao"]) is None
    assert "outra pessoa" in _cq().regras_ocorrencia(dele, ["anotacao", "geom"])
    assert "encerrada" in _cq("concluida").regras_ocorrencia(minha, ["anotacao"])
    # Ciência: só o autor da carga apontada, e vale com a passagem de CQ encerrada.
    assert _cq("concluida").regras_ocorrencia(dele, ["ciente_em", "ciente_por"]) is None
    assert "só quem fez a carga" in _cq().regras_ocorrencia(minha, ["ciente_em", "ciente_por"])


def test_rotulos_do_cq():
    p = _cq()
    assert p._rotulo("cq_amostra", {"id_carga_trabalho": 4001}, {}) == "Amostra da carga 4001 em 2534-1"
    assert p._rotulo("cq_inspecao", None, {"campos": {"id_lote_etapa": 12}}) == "Ocorrência em 2534-1"


def test_juntar_nao_junta_apagar_com_editar():
    itens = [
        _item(1, "cq_inspecao", "o1", {"anotacao": "a"}, "x1"),
        _item(2, "cq_inspecao", "o1", {"anotacao": "b"}, "x2"),
        _item(3, "cq_inspecao", "o1", {}, "x3", op="delete"),
    ]
    passos = push.juntar(itens)
    assert [(t, g["operacao"], len(g["itens"])) for t, g in passos] == [("envio", "update", 2), ("envio", "delete", 1)]
