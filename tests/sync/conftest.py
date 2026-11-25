"""Workspace de teste: um GeoPackage numa pasta temporária, com um cenário pequeno gravado como se viesse do pull.

Cenário (conta `u_apm`, DF):
- folha 2534 na revisão 1, aquisição em andamento (passagem 11): três cargas minhas pendentes, em fila de oeste a
  leste (1001, 1002, 1003), e uma de outra pessoa (1009);
- folha 2535, revisão 0, aquisição pendente (passagem 21): duas cargas sem responsável (2001, 2002), na minha fila;
- folha 2536, passagem 31 já concluída pelo supervisor: uma carga minha ainda pendente (3001).
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from feixe.sync import geometria
from feixe.sync.workspace import Workspace

USUARIO = "u_apm"
VERSAO = dt.datetime(2026, 11, 20, 12, 0, 0, 123456, tzinfo=dt.timezone.utc)


def _u() -> str:
    return str(uuid.uuid4())


def celula(x: float, y: float, lado: float = 0.05) -> bytes:
    return geometria.retangulo(x, y, x + lado, y + lado)


def carga(id_, le, resp, x, y, concluido=False, concluido_em=None):
    return {
        "id": id_, "uuid": _u(), "id_lote_etapa": le, "id_atividade": 100, "uf": "DF", "responsavel": resp,
        "geom": celula(x, y), "geocodigo": None, "concluido": concluido, "concluido_em": concluido_em,
        "criado_em": VERSAO, "criado_por": "sup", "atualizado_em": VERSAO, "atualizado_por": "sup",
    }  # fmt: skip


def _aud():
    return {"criado_em": VERSAO, "criado_por": "sup", "atualizado_em": VERSAO, "atualizado_por": "sup"}


def popular(ws: Workspace) -> None:
    with ws.transacao() as ex:
        ex.gravar_remoto("tema", {"id": 1, "nome": "Hidrografia", "ativo": True, "atualizado_em": VERSAO})
        ex.gravar_remoto("fase", {"codigo": "aquisicao", "nome": "Aquisição", "ordem": 1,
                                  "status_nacional": "EM_PRODUCAO"})  # fmt: skip
        ex.gravar_remoto("atividade", {"id": 100, "cod_projeto": 5, "id_tema": 1, "fase": "aquisicao",
                                       "nome": "Aquisição BC100 - Hidrografia", "geracao": "grade",
                                       "grade_nivel": 5000, "ativo": True, "atualizado_em": VERSAO})  # fmt: skip
        ex.gravar_remoto("fluxo_etapa", {"id": 10, "id_fluxo": 1, "ordem": 1, "fase": "aquisicao", "nome": "Aquisição",
                                         "atualizado_em": VERSAO})  # fmt: skip
        for id_lote, nome in ((1, "2534"), (2, "2535"), (3, "2536")):
            ex.gravar_remoto("lote", {"id": id_lote, "uuid": _u(), "cod_projeto": 5, "id_tema": 1, "id_fluxo": 1,
                                      "uf": "DF", "tipo": "folha", "id_articulacao_scn": 900 + id_lote, "nome": nome,
                                      "geom": None, **_aud()})  # fmt: skip
        for id_le, id_lote, rev, sit in ((11, 1, 1, "em_andamento"), (21, 2, 0, "pendente"), (31, 3, 1, "concluida")):
            ex.gravar_remoto("lote_etapa", {"id": id_le, "uuid": _u(), "id_lote": id_lote, "id_fluxo_etapa": 10,
                                            "uf": "DF", "instancia": 1, "revisao": rev, "situacao": sit,
                                            "expor_ocorrencias": False, **_aud()})  # fmt: skip
        for c in (
            carga(1001, 11, USUARIO, -47.90, -15.80),
            carga(1002, 11, USUARIO, -47.80, -15.80),
            carga(1003, 11, USUARIO, -47.60, -15.80),
            carga(1009, 11, "u_outro", -47.85, -15.80),
            carga(2001, 21, None, -47.70, -15.70),
            carga(2002, 21, None, -47.65, -15.70),
            carga(3001, 31, USUARIO, -47.89, -15.80),
        ):
            ex.gravar_remoto("carga_trabalho", c)
        ex.gravar_remoto("fila_folha", {"id": 501, "uuid": _u(), "id_lote_etapa": 21, "uf": "DF",
                                        "responsavel": USUARIO, "ordem": 1, **_aud()})  # fmt: skip


@pytest.fixture
def ws(tmp_path):
    w = Workspace.abrir("dev", USUARIO, "DF", raiz=str(tmp_path))
    popular(w)
    yield w
    w.fechar()
