"""D0: o que o modelo ganhou para a fase D (002, 004, 006). Roda nos dois bancos, dentro de transações desfeitas.

Padrão do plano na etapa de CQ (D-135), fração crítica gravada no plano (D-62), um plano por atividade na passagem
(D-83), passagem de CQ e carga avaliada da ocorrência (D-66) e tratado_em/tratado_por.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from feixe.core import grade

from tests.db.migracoes import aplicar
from tests.db.test_grants import _como, mundo  # noqa: F401 (fixture)
from tests.db.test_regras import Cenario, _erro, _uid, _um

pytestmark = pytest.mark.db


@pytest.fixture
def cen(banco):
    aplicar(banco)
    with banco.cursor() as cur:
        yield Cenario(cur)


def _ocorrencia(cur, lote, x, y, carga=None, lote_etapa=None, **extra):
    cols = {"uuid": _uid(), "id_lote": lote, "id_carga_trabalho": carga, "id_lote_etapa": lote_etapa,
            "elemento": "Omissão", **extra}  # fmt: skip
    nomes = ", ".join(cols)
    marcas = ", ".join(["%s"] * len(cols))
    cur.execute(
        f"INSERT INTO mapcartacomp.cq_inspecao ({nomes}, geom) "
        f"VALUES ({marcas}, ST_SetSRID(ST_MakePoint(%s, %s), 4674)) "
        "RETURNING id, id_lote_etapa, id_carga_avaliada",
        (*cols.values(), x, y),
    )
    return cur.fetchone()


def test_padrao_do_plano_na_etapa_e_fracao_no_plano(cen):
    cur = cen.cur
    etapa = cen.etapa["cq"]
    # Nulos por padrão: sem padrão na etapa, o supervisor escolhe.
    cur.execute("SELECT nivel_inspecao, lqa, fracao_critica FROM mapcartacomp.fluxo_etapa WHERE id = %s", (etapa,))
    assert cur.fetchone() == (None, None, None)
    cur.execute(
        "UPDATE mapcartacomp.fluxo_etapa SET nivel_inspecao = 'II', lqa = 2.5, fracao_critica = 2.5 WHERE id = %s",
        (etapa,),
    )
    cq = cen.passagem("cq", "em_andamento")
    p = cen.plano(cq, "Omissão", 1)
    cur.execute(
        "UPDATE mapcartacomp.cq_plano p SET nivel_inspecao = fe.nivel_inspecao, lqa = fe.lqa, "
        "fracao_critica = fe.fracao_critica FROM mapcartacomp.lote_etapa le "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa WHERE le.id = p.id_lote_etapa AND p.id = %s "
        "RETURNING p.nivel_inspecao, p.lqa, p.fracao_critica",
        (p,),
    )
    assert cur.fetchone() == ("II", 2.5, 2.5)
    # Texto aberto no nível; LQA e fração crítica só positivos.
    cur.execute("UPDATE mapcartacomp.fluxo_etapa SET nivel_inspecao = 'S-3' WHERE id = %s", (etapa,))
    _erro(cur, psycopg2.IntegrityError, cur.execute,
          "UPDATE mapcartacomp.fluxo_etapa SET lqa = 0 WHERE id = %s", (etapa,))  # fmt: skip
    _erro(cur, psycopg2.IntegrityError, cur.execute,
          "UPDATE mapcartacomp.cq_plano SET fracao_critica = 100 WHERE id = %s", (p,))  # fmt: skip


def test_um_plano_por_atividade_na_passagem(cen):
    cq1 = cen.passagem("cq", "concluida")
    cq2 = cen.passagem("cq", "em_andamento", instancia=2)
    cen.plano(cq1, "Omissão", 0)
    cen.plano(cq1, "Comissão", 0)
    cen.plano(cq2, "Omissão", 0)  # nova passagem (revisão seguinte ou nível III) tem o seu plano
    _erro(cen.cur, psycopg2.IntegrityError, cen.plano, cq1, "Omissão", 0)


def test_celulas_de_passagens_anteriores_do_mesmo_lote_e_atividade(cen):
    """O sorteio do D2 exclui as células já sorteadas no mesmo lote e atividade: o geocódigo da carga de CQ basta, e a
    mesma célula pode voltar numa passagem seguinte (o índice único é por passagem)."""
    cur = cen.cur
    cq1 = cen.passagem("cq", "concluida")
    cq2 = cen.passagem("cq", "em_andamento", instancia=2)
    geocodigo = grade.celula_do_ponto(5000, -44.25, -19.75)
    p1 = cen.plano(cq1, "Omissão", 0)
    cen.carga(cq1, plano=p1, geocodigo=geocodigo)
    cen.carga(cq2, plano=cen.plano(cq2, "Omissão", 0), geocodigo=geocodigo)
    cur.execute(
        "SELECT c.geocodigo FROM mapcartacomp.carga_trabalho c JOIN mapcartacomp.lote_etapa le "
        "ON le.id = c.id_lote_etapa WHERE le.id_lote = %s AND c.id_atividade = %s AND c.id_cq_plano IS NOT NULL "
        "AND le.id <> %s",
        (cen.lote, cen.ativ_cq["Omissão"], cq2),
    )
    assert [r[0] for r in cur.fetchall()] == [geocodigo]


def test_ocorrencia_sabe_a_passagem_e_a_carga_avaliada(cen):
    cur = cen.cur
    aq1 = cen.passagem("aquisicao", "concluida")
    autor1 = cen.carga(aq1, responsavel="apm_1", concluido=True)
    outra = cen.carga(aq1, responsavel="apm_x", concluido=True, x=-44.3)
    cq1 = cen.passagem("cq", "concluida")
    p1 = cen.plano(cq1, "Omissão", 0)
    amostra1 = cen.carga(cq1, plano=p1)
    # Pela carga de CQ: passagem derivada; carga avaliada = a da aquisição (revisão 1) que contém o ponto.
    _, le, avaliada = _ocorrencia(cur, cen.lote, -44.475, -19.975, carga=amostra1)
    assert (le, avaliada) == (cq1, autor1)
    # Sem carga, com a passagem: deriva só a carga avaliada. Fora de qualquer carga da revisão: nula.
    assert _ocorrencia(cur, cen.lote, -44.275, -19.975, lote_etapa=cq1)[1:] == (cq1, outra)
    assert _ocorrencia(cur, cen.lote, -44.0, -19.5, lote_etapa=cq1)[1:] == (cq1, None)
    # A carga avaliada informada é mantida (o plugin decide quando sabe).
    assert _ocorrencia(cur, cen.lote, -44.475, -19.975, lote_etapa=cq1, id_carga_avaliada=outra)[2] == outra

    # Revisão 2 (nova aquisição, outro operador) e CQ 2: a ocorrência aponta a carga da revisão 2, não a da 1.
    aq2 = cen.passagem("aquisicao", "concluida", instancia=2)
    autor2 = cen.carga(aq2, responsavel="apm_2", concluido=True)
    cq2 = cen.passagem("cq", "em_andamento", instancia=2)
    assert _um(cur, "SELECT revisao FROM mapcartacomp.lote_etapa WHERE id = %s", (cq2,)) == 2
    id_, le, avaliada = _ocorrencia(cur, cen.lote, -44.475, -19.975, lote_etapa=cq2)
    assert (le, avaliada) == (cq2, autor2)
    # Mover o ponto recalcula a carga avaliada.
    cur.execute(
        "UPDATE mapcartacomp.cq_inspecao SET geom = ST_SetSRID(ST_MakePoint(-44.0, -19.5), 4674) WHERE id = %s "
        "RETURNING id_carga_avaliada",
        (id_,),
    )
    assert cur.fetchone()[0] is None

    # Carga de produção (convertida do DF) não dá passagem; passagem de outro lote é recusada.
    assert _ocorrencia(cur, cen.lote, -44.475, -19.975, carga=autor1)[1:] == (None, None)
    outro_lote = _um(
        cur,
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome) "
        "VALUES (%s, 5, %s, %s, 'DF', 'livre', 'LIVRE') RETURNING id",
        (_uid(), cen.tema, cen.fluxo),
    )
    _erro(cur, psycopg2.IntegrityError, _ocorrencia, cur, outro_lote, -44.475, -19.975, lote_etapa=cq1)


def test_tratado_em_e_por(cen):
    cur = cen.cur
    cq = cen.passagem("cq", "em_andamento")
    id_ = _ocorrencia(cur, cen.lote, -44.475, -19.975, lote_etapa=cq)[0]
    sql = "SELECT tratado_em IS NOT NULL, tratado_por = current_user FROM mapcartacomp.cq_inspecao WHERE id = %s"
    assert _um(cur, "SELECT tratado_em FROM mapcartacomp.cq_inspecao WHERE id = %s", (id_,)) is None
    cur.execute("UPDATE mapcartacomp.cq_inspecao SET tratado = true WHERE id = %s", (id_,))
    cur.execute(sql, (id_,))
    assert cur.fetchone() == (True, True)
    cur.execute("UPDATE mapcartacomp.cq_inspecao SET tratado = false WHERE id = %s", (id_,))
    cur.execute("SELECT tratado_em, tratado_por FROM mapcartacomp.cq_inspecao WHERE id = %s", (id_,))
    assert cur.fetchone() == (None, None)
    # Marcação offline sincronizada depois: a hora e a pessoa que vieram ficam.
    cur.execute(
        "UPDATE mapcartacomp.cq_inspecao SET tratado = true, tratado_em = '2026-11-20 10:00+00', tratado_por = 'apm_1' "
        "WHERE id = %s RETURNING tratado_em = '2026-11-20 10:00+00', tratado_por",
        (id_,),
    )
    assert cur.fetchone() == (True, "apm_1")
    # Inserida já tratada (push de uma criada offline): mantém a hora; sem hora, agora.
    id2 = _ocorrencia(cur, cen.lote, -44.475, -19.975, lote_etapa=cq, tratado=True)[0]
    cur.execute(sql, (id2,))
    assert cur.fetchone() == (True, True)


def test_avaliador_e_apm_gravam_o_cq_com_os_grants(mundo):  # noqa: F811
    """Com os GRANTs gerados: o supervisor configura o padrão da etapa, o avaliador registra a ocorrência, o operador dá
    ciência e a correção de inspeção marca tratada."""
    cur, d = mundo
    # A passagem, o plano e a carga de CQ vêm da supervisão (online); aqui, prontos.
    le = _um(
        cur,
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, situacao) "
        "VALUES (%s, %s, %s, 'em_andamento') RETURNING id",
        (str(uuid.uuid4()), d["DF"]["lote"], d["DF"]["etapa_cq"]),
    )
    plano = _um(
        cur,
        "INSERT INTO mapcartacomp.cq_plano (uuid, id_lote_etapa, id_atividade, nivel_inspecao, lqa, fracao_critica, "
        "numero_aceitacao_ac) VALUES (%s, %s, %s, 'II', 2.5, 2.5, 0) RETURNING id",
        (str(uuid.uuid4()), le, d["ativ_cq"]),
    )
    carga = _um(
        cur,
        "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, id_cq_plano, responsavel, geom) "
        "SELECT %s, %s, %s, %s, 'feixe_teste_df', geom FROM mapcartacomp.carga_trabalho WHERE id = %s RETURNING id",
        (str(uuid.uuid4()), le, d["ativ_cq"], plano, d["DF"]["carga"]),
    )
    _como(cur, "feixe_teste_df")
    cur.execute(
        "UPDATE mapcartacomp.fluxo_etapa SET nivel_inspecao = 'II', lqa = 2.5 WHERE id = %s", (d["DF"]["etapa_cq"],)
    )
    assert cur.rowcount == 1
    cur.execute("UPDATE mapcartacomp.cq_plano SET fracao_critica = 4 WHERE id = %s", (plano,))
    assert cur.rowcount == 1
    cur.execute(
        "INSERT INTO mapcartacomp.cq_inspecao (uuid, id_lote, id_carga_trabalho, elemento, geom) "
        "SELECT %s, %s, %s, 'Nome Geográfico', ST_PointOnSurface(geom) FROM mapcartacomp.carga_trabalho "
        "WHERE id = %s RETURNING id, id_lote_etapa",
        (str(uuid.uuid4()), d["DF"]["lote"], carga, carga),
    )
    ocorrencia, passagem = cur.fetchone()
    assert passagem == le
    cur.execute(
        "UPDATE mapcartacomp.cq_inspecao SET ciente_em = now(), ciente_por = current_user WHERE id = %s", (ocorrencia,)
    )
    cur.execute("UPDATE mapcartacomp.cq_inspecao SET tratado = true WHERE id = %s RETURNING tratado_por", (ocorrencia,))
    assert cur.fetchone()[0] == "feixe_teste_df"
