"""D3c e D5: regras da barra do Feixe para o CQ e a correção de inspeção, sem o QGIS: que ações aparecem, a barra de
status e as mensagens que levam a pessoa ao próximo passo (D-136)."""

from feixe.ui import regras


def test_acoes_do_avaliador_so_com_amostras_e_ciente_so_com_ocorrencia():
    assert regras.acoes_visiveis({}) == {
        "proxima_amostra": False, "conforme": False, "nao_conforme": False, "ocorrencia": False, "ciente": False,
        "proxima_ocorrencia": False, "tratada": False, "proxima": False, "pular": False, "concluir": False,
    }  # fmt: skip
    avaliador = regras.acoes_visiveis({"amostras": 20, "pendentes": 0, "ciencia": 0}, "cq")
    assert all(avaliador[a] for a in regras.ACOES_AVALIADOR) and not avaliador["ciente"]
    # D-148: a barra de avaliação só no modo Avaliar (o grupo Controle de qualidade ligado).
    for modo in (None, "execucao", "supervisao"):
        fora = regras.acoes_visiveis({"amostras": 20}, modo)
        assert not any(fora[a] for a in regras.ACOES_AVALIADOR)
    apm = regras.acoes_visiveis({"amostras": 0, "pendentes": 0, "ciencia": 2}, "execucao")
    assert apm["ciente"] and not any(apm[a] for a in regras.ACOES_AVALIADOR)
    assert regras.acoes_visiveis(None)["ciente"] is False


def test_barra_da_execucao_so_no_modo_executar():
    # D-150: próxima, pular e concluir, Ciente e as da correção só com o grupo Execução ligado; sem o grupo, nada.
    cheio = {"amostras": 20, "ciencia": 2, "correcao": 3}
    exe = regras.acoes_visiveis(cheio, "execucao")
    assert all(exe[a] for a in (*regras.ACOES_EXECUCAO, "ciente", *regras.ACOES_CORRECAO))
    assert not any(exe[a] for a in regras.ACOES_AVALIADOR)
    for modo in (None, "cq", "supervisao"):
        vis = regras.acoes_visiveis(cheio, modo)
        assert not any(vis[a] for a in (*regras.ACOES_EXECUCAO, "ciente", *regras.ACOES_CORRECAO)), modo
    assert not any(regras.acoes_visiveis(cheio, None).values())


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


def test_correcao_so_para_quem_esta_com_folha_na_correcao():
    vis = regras.acoes_visiveis({"amostras": 0, "ciencia": 0, "correcao": 40, "correcao_pendentes": 0}, "execucao")
    # Com tudo tratado as ações continuam: desmarcar vale enquanto a etapa está aberta.
    assert all(vis[a] for a in regras.ACOES_CORRECAO) and not vis["ciente"] and not vis["conforme"]
    assert not any(regras.acoes_visiveis({"correcao": 0})[a] for a in regras.ACOES_CORRECAO)


def test_texto_da_barra_de_status_na_correcao():
    p = {"folha_revisao": "2534-3", "tratadas": 12, "total": 40, "pendentes": 28}
    assert regras.texto_status(p) == "Feixe · Correção 2534-3 · 12/40 tratadas"


def _tratada(tratadas, total, proxima, tratado=True, fila=None):
    return {
        "ocorrencia": {"tratado": tratado, "elemento": "Omissão", "folha_revisao": "2534-1"},
        "progresso": {"folha_revisao": "2534-3", "tratadas": tratadas, "total": total,
                      "pendentes": total - tratadas},
        "proxima": proxima, "fila": fila,
    }  # fmt: skip


def test_tratada_leva_a_proxima_e_a_ultima_diz_que_o_supervisor_decide():
    prox = {"elemento": "Comissão", "folha_revisao": "2534-2"}
    assert regras.mensagem_tratada(_tratada(12, 40, prox)) == (
        "Tratada · Omissão · 2534-3 12/40. Próxima: Comissão na 2534-2."
    )
    fim = regras.mensagem_tratada(_tratada(40, 40, None))
    assert fim.startswith("Tratada · Omissão · 2534-3 40/40. ") and "supervisor" in fim and "Esperando" in fim
    desfeita = regras.mensagem_tratada(_tratada(39, 40, prox, tratado=False))
    assert desfeita.startswith("Tratamento desfeito · Omissão · 2534-3 39/40.")
    fila = regras.mensagem_tratada(_tratada(40, 40, None, fila={"folha_revisao": "2601-1", "atribuidas": 30}))
    assert "A próxima folha da sua fila é a 2601-1 (30 cargas)" in fila
