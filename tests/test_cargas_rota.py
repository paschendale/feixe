"""B2: rotas de minhas cargas, com a camada de dados substituída (a de verdade é testada em tests/db/test_cargas.py)."""

from contextlib import contextmanager

import pytest
from feixe.core.dados import ErroDados
from feixe.core.dados import cargas as dc
from feixe.server.api import Contexto, criar_roteador

PROG = {"id_lote_etapa": 7, "folha_revisao": "2534-1", "concluidas": 35, "total": 93}
CARGA = {"id": 1, "id_lote_etapa": 7, "concluido": True, "xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1}


@pytest.fixture
def montar(monkeypatch):
    chamadas = {"sql": [], "qgis": [], "eventos": []}
    monkeypatch.setattr(dc, "concluir", lambda ex, i: {"carga": {**CARGA, "id": i}, "progresso": PROG})
    monkeypatch.setattr(dc, "proxima", lambda ex, ref: {**CARGA, "id": 2, "concluido": False} if ref != 99 else None)
    monkeypatch.setattr(dc, "progresso", lambda ex, le: PROG)
    monkeypatch.setattr(dc, "uma", lambda ex, i: {**CARGA, "id": i, "responsavel": "u_1"})
    monkeypatch.setattr(dc, "minhas", lambda ex, le, concl: chamadas["sql"].append((le, concl)) or [])

    def desfazer(ex, i):
        raise ErroDados("só dá para desfazer até 24 horas depois de concluir")

    monkeypatch.setattr(dc, "desfazer", desfazer)

    def fazer(papeis, com_qgis=True):
        @contextmanager
        def tx():
            yield object()

        ctx = Contexto(
            transacao=tx,
            publicar=lambda e, d: chamadas["eventos"].append((e, d)),
            qgis=(lambda nome, *a: chamadas["qgis"].append(nome)) if com_qgis else None,
        )
        ctx._eu = {"papeis": papeis, "uf": "DF", "perfis": []}
        return criar_roteador(ctx), chamadas

    return fazer


def test_concluir_avisa_o_painel_e_o_qgis(montar):
    r, ch = montar(["apm"])
    status, obj = r.despachar("POST", "/api/cargas/5/concluir", {}, None)
    assert status == 200 and obj["carga"]["id"] == 5 and obj["progresso"]["concluidas"] == 35
    assert ch["eventos"][0][0] == "carga" and ch["qgis"] == ["cargas_mudaram"]


def test_recusa_de_desfazer_volta_como_409(montar):
    r, _ = montar(["apm"])
    status, obj = r.despachar("POST", "/api/cargas/5/desfazer", {}, None)
    assert status == 409 and "24 horas" in obj["erro"]


def test_proxima_foca_no_qgis_e_sem_pendente_devolve_nulo(montar):
    r, ch = montar(["apm"])
    status, obj = r.despachar("POST", "/api/cargas/proxima", {}, {"referencia": 5})
    assert status == 200 and obj["carga"]["id"] == 2 and ch["qgis"] == ["focar_carga"]
    status, obj = r.despachar("POST", "/api/cargas/proxima", {}, {"referencia": 99})
    assert status == 200 and obj == {"carga": None, "progresso": None}


def test_sem_qgis_concluir_funciona_e_zoom_nao(montar):
    r, _ = montar(["apm"], com_qgis=False)
    assert r.despachar("POST", "/api/cargas/5/concluir", {}, None)[0] == 200
    assert r.despachar("POST", "/api/cargas/5/zoom", {}, None)[0] == 503


def test_lista_valida_filtro_e_consulta_nao_entra(montar):
    r, ch = montar(["apm"])
    assert r.despachar("GET", "/api/cargas", {"situacao": "pendente", "lote_etapa": "7"}, None)[0] == 200
    assert ch["sql"] == [(7, False)]
    assert r.despachar("GET", "/api/cargas", {"situacao": "talvez"}, None)[0] == 400
    assert r.despachar("GET", "/api/cargas", {"lote_etapa": "x"}, None)[0] == 400
    r, _ = montar(["consulta"])
    assert r.despachar("POST", "/api/cargas/5/concluir", {}, None)[0] == 403


def test_gerar_varias_passagens_com_recusa_de_uma(montar, monkeypatch):
    def gerar(ex, le, previa, uf):
        if le == 2:
            raise ErroDados("2535-0: esta etapa já tem cargas")
        r = {"id_lote_etapa": le, "folha_revisao": "2534-0", "celulas": 112, "gravadas": 0 if previa else 112}
        return {**r, "previa": [{"geocodigo": "5KME1N1", "wkt": "MULTIPOLYGON EMPTY"}]} if previa else r

    monkeypatch.setattr(dc, "gerar_pela_grade", gerar)
    r, ch = montar(["supervisor"])
    status, obj = r.despachar("POST", "/api/cargas/gerar", {}, {"lote_etapas": [1, 2], "previa": True})
    assert status == 200 and [x["celulas"] for x in obj["resultados"]] == [112] and "previa" not in obj["resultados"][0]
    assert obj["erros"] == [{"id_lote_etapa": 2, "erro": "2535-0: esta etapa já tem cargas"}]
    assert ch["qgis"] == ["previa_cargas"] and ch["eventos"] == []
    status, obj = r.despachar("POST", "/api/cargas/gerar", {}, {"lote_etapas": [1], "previa": False})
    assert obj["resultados"][0]["gravadas"] == 112 and [e for e, _ in ch["eventos"]] == ["carga", "lote"]
    assert r.despachar("POST", "/api/cargas/gerar", {}, {"lote_etapas": []})[0] == 400
    r, _ = montar(["apm"])
    assert r.despachar("POST", "/api/cargas/gerar", {}, {"lote_etapas": [1]})[0] == 403
