"""D3c: regras da barra do Feixe para o CQ, sem o QGIS: que ações aparecem, a barra de status e as mensagens que levam
a pessoa ao próximo passo (D-136)."""

from feixe.ui import regras


def test_acoes_do_avaliador_so_com_amostras_e_ciente_so_com_ocorrencia():
    assert regras.acoes_visiveis({}) == {
        "proxima_amostra": False, "conforme": False, "nao_conforme": False, "ocorrencia": False, "ciente": False,
    }  # fmt: skip
    avaliador = regras.acoes_visiveis({"amostras": 20, "pendentes": 0, "ciencia": 0})
    assert all(avaliador[a] for a in regras.ACOES_AVALIADOR) and not avaliador["ciente"]
    apm = regras.acoes_visiveis({"amostras": 0, "pendentes": 0, "ciencia": 2})
    assert apm["ciente"] and not any(apm[a] for a in regras.ACOES_AVALIADOR)
    assert regras.acoes_visiveis(None)["ciente"] is False


def test_texto_da_barra_de_status():
    p = {"folha_revisao": "2534-1", "concluidas": 7, "total": 20}
    assert regras.texto_status(p, cq=True) == "Feixe · CQ 2534-1 · 7/20 amostras"
    assert regras.texto_status(p) == "Feixe · 2534-1 · 7/20"
    assert regras.texto_status(None, cq=True) == "Feixe"


def _avaliada(status, proxima):
    return {
        "amostra": {"status": status, "elemento": "Omissão", "folha_revisao": "2534-1"},
        "progresso": {"folha_revisao": "2534-1", "concluidas": 8, "total": 20},
        "proxima": proxima,
    }


def test_avaliar_leva_a_proxima_e_a_ultima_diz_o_que_vem_depois():
    prox = {"carga": {"id": 2}, "amostra": {"elemento": "Comissão", "folha_revisao": "2534-1"}}
    assert regras.mensagem_avaliada(_avaliada(0, prox)) == (
        "Amostra não conforme · Omissão · 2534-1 8/20. Próxima: Comissão na 2534-1."
    )
    fim = regras.mensagem_avaliada(_avaliada(1, None))
    assert fim.startswith("Amostra conforme · Omissão · 2534-1 8/20. ") and "supervisor" in fim


def test_mensagem_de_ocorrencia_lembra_a_decisao_so_com_a_amostra_pendente():
    o = {"elemento": "Omissão", "folha_revisao": "2534-1"}
    pend = regras.mensagem_ocorrencia({"ocorrencia": o, "amostra": {"status": None}})
    assert pend == (
        "Ocorrência registrada · Omissão · 2534-1. Ao terminar esta amostra, marque Conforme ou Não conforme."
    )
    assert regras.mensagem_ocorrencia({"ocorrencia": o, "amostra": {"status": 0}}) == (
        "Ocorrência registrada · Omissão · 2534-1."
    )


def test_mensagem_de_ciente_diz_quantas_faltam():
    o = {"elemento": "Omissão", "folha_revisao": "2534-1"}
    assert regras.mensagem_ciente(o, 1) == "Ciente · Omissão · 2534-1. Falta 1 para dar ciência."
    assert regras.mensagem_ciente(o, 3).endswith("Faltam 3 para dar ciência.")
    assert regras.mensagem_ciente(o, 0).endswith("Não há mais ocorrências esperando a sua ciência.")
