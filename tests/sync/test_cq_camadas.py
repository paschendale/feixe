"""D3c: o que as camadas do CQ no QGIS leem do workspace, sem o QGIS: as views juntadas (amostras e ocorrências), os
filtros das camadas (o mesmo SQL que o OGR aplica como `subsetString`), os subgrupos da execução com os elementos e a
lista de correção, e o estado que a barra usa para mostrar as ações. Cenário: o de `test_cq_execucao.py`."""

from __future__ import annotations

import sqlite3

from feixe.core.dados.local import cq as lq
from feixe.core.dados.local import grupos as lg
from feixe.sync import esquema
from feixe.sync.workspace import Workspace

from tests.sync.conftest import USUARIO, VERSAO, popular
from tests.sync.test_cq_execucao import cq  # noqa: F401 - fixture

_FASE_CQ = {"codigo": "cq", "nome": "Controle de qualidade", "ordem": 3, "status_nacional": "EM_CQ"}


def _ids(ex, tabela, filtro, coluna="id"):
    return sorted(r[coluna] for r in ex.todos(f"SELECT {coluna} FROM {tabela} WHERE {filtro}"))


def test_view_de_amostras_com_status_plano_e_progresso(ws, cq):  # noqa: F811
    with ws.transacao() as ex:
        lq.avaliar(ex, 9001, 0, "faltou um trecho")
    with ws.leitura() as ex:
        linhas = {r["id"]: r for r in ex.todos(f"SELECT * FROM {esquema.VW_AMOSTRA_INFO}")}
    # Só as minhas cargas de CQ (a 4003 é de outro avaliador), abertas e encerradas: a camada filtra as abertas.
    assert set(linhas) == {4001, 4002, 4009}
    a = linhas[4001]
    assert (a["id_amostra"], a["status"], a["observacao"], a["elemento"]) == (9001, 0, "faltou um trecho", "Omissão")
    assert (a["folha_revisao"], a["plano_n"], a["plano_ac"], a["plano_letra"]) == ("2534-1", 3, 0, "B")
    assert (int(a["amostras_na_folha"]), int(a["avaliadas_na_folha"])) == (2, 1)
    assert linhas[4002]["status"] is None


def test_view_de_ocorrencias_pelo_uuid_com_folha_amostra_e_autor(ws, cq):  # noqa: F811
    with ws.transacao() as ex:
        nova = lq.registrar(ex, -47.89, -15.79, 4001, "offline")["ocorrencia"]["uuid"]
    with ws.leitura() as ex:
        linhas = {r["uuid"]: r for r in ex.todos(f"SELECT * FROM {esquema.VW_OCORRENCIA_INFO}")}
    assert linhas[cq["autor"]]["autor"] == USUARIO and linhas[cq["autor"]]["folha_revisao"] == "2534-1"
    assert linhas[nova]["id_carga_amostra"] == 4001 and linhas[nova]["autor"] is None  # o banco deriva no push


def test_filtros_das_camadas_do_cq(ws, cq):  # noqa: F811
    with ws.transacao() as ex:
        nova = lq.registrar(ex, -47.89, -15.79, 4001, "minha")["ocorrencia"]["uuid"]
    with ws.leitura() as ex:
        # Amostras: as minhas cargas de CQ da atividade em passagens abertas (a 4009 é de passagem encerrada).
        assert _ids(ex, "carga_trabalho", lg.filtro_amostras(200)) == [4001, 4002]
        assert _ids(ex, "carga_trabalho", lg.filtro_amostras(100)) == []
        # Ocorrências do avaliador: as das minhas amostras abertas (as vindas da CCAR estão na 4003, de outro).
        assert _ids(ex, "cq_inspecao", lg.filtro_ocorrencias(200), "uuid") == [nova]
        # Para ciência: a que aponta a minha carga 1001, sem ciência.
        assert _ids(ex, "cq_inspecao", lg.FILTRO_CIENCIA, "uuid") == [cq["autor"]]
        # Correção: nada sem "incluir correções a serem feitas".
        assert _ids(ex, "cq_inspecao", lg.filtro_correcoes(), "uuid") == []
    with ws.transacao() as ex:
        lq.ciente(ex, cq["autor"])
        ex.gravar_remoto("lote_etapa", {**ex.um("SELECT * FROM lote_etapa WHERE id = 13"), "expor_ocorrencias": True,
                                        "atualizado_em": VERSAO})  # fmt: skip
    with ws.leitura() as ex:
        assert _ids(ex, "cq_inspecao", lg.FILTRO_CIENCIA, "uuid") == []
        # A revisão 13 (com carga minha) expõe as não tratadas da folha 2534: todas menos a tratada.
        esperadas = sorted([cq["autor"], cq["outro"], nova])
        assert _ids(ex, "cq_inspecao", lg.filtro_correcoes(), "uuid") == esperadas
        assert _ids(ex, "cq_inspecao", lg.filtro_correcoes([100]), "uuid") == esperadas
        assert _ids(ex, "cq_inspecao", lg.filtro_correcoes([999]), "uuid") == []


def test_subgrupos_da_execucao_com_elementos_e_correcoes(ws, cq):  # noqa: F811
    with ws.transacao() as ex:
        ex.gravar_remoto("fase", _FASE_CQ)
        ex.gravar_remoto("lote_etapa", {**ex.um("SELECT * FROM lote_etapa WHERE id = 13"), "expor_ocorrencias": True,
                                        "atualizado_em": VERSAO})  # fmt: skip
    with ws.leitura() as ex:
        grupos = lg.execucao(ex)
    por_fase = {g["fase"]: g for g in grupos}
    assert por_fase["cq"]["rotulo"] == "CQ · Hidrografia"
    assert por_fase["cq"]["elementos"] == [{"id_atividade": 200, "elemento": "Omissão"}]
    assert por_fase["aquisicao"]["expor_ocorrencias"] is True
    plano = lg.plano_execucao(grupos)
    assert [p["tipo"] for p in plano] == ["producao", "cq"] and plano[0]["correcoes"]


def test_estado_do_cq_para_a_barra(ws, cq):  # noqa: F811
    with ws.leitura() as ex:
        assert lg.estado_cq(ex) == {"amostras": 2, "pendentes": 2, "ciencia": 1}
        assert sorted(lg.cargas_cq_pendentes(ex)) == [4001, 4002, 4009]
        assert lg.e_cq(ex, 12) and not lg.e_cq(ex, 11) and not lg.e_cq(ex, None)
    with ws.transacao() as ex:
        lq.avaliar(ex, 9001, 1)
        lq.ciente(ex, cq["autor"])
    with ws.leitura() as ex:
        assert lg.estado_cq(ex) == {"amostras": 2, "pendentes": 1, "ciencia": 0}


def test_migracao_5_para_6_cria_as_views_do_cq(tmp_path):
    w = Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path))
    popular(w)
    caminho = w.caminho
    w.fechar()
    conn = sqlite3.connect(caminho)
    for vw in (esquema.VW_AMOSTRA_INFO, esquema.VW_OCORRENCIA_INFO):
        conn.execute(f"DROP VIEW {vw}")
        conn.execute("DELETE FROM gpkg_contents WHERE table_name = ?", (vw,))
    conn.execute("UPDATE meta SET valor = '5' WHERE chave = 'versao_esquema'")
    conn.commit()
    conn.close()
    w = Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path))
    try:
        with w.leitura() as ex:
            assert ex.meta("versao_esquema") == str(esquema.VERSAO)
            assert ex.um("SELECT count(*) AS n FROM carga_trabalho")["n"] > 0  # migrou, não recriou
            nomes = {r["table_name"] for r in ex.todos("SELECT table_name FROM gpkg_contents")}
            assert {esquema.VW_AMOSTRA_INFO, esquema.VW_OCORRENCIA_INFO} <= nomes
            assert ex.todos(f"SELECT * FROM {esquema.VW_AMOSTRA_INFO}") == []
    finally:
        w.fechar()
