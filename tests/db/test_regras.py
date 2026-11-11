"""A2: regras no banco (triggers, derivações e views). Roda nos dois bancos, dentro de transações desfeitas.

Cenário: fluxo DF com aquisição (conta revisão, repetível) > CQ (repetível) > correção de inspeção > envio à GCQ,
na folha 2534. Cada teste monta o que precisa sobre ele.
"""

from __future__ import annotations

import uuid

import pytest
from feixe.core import grade

from tests.db.migracoes import aplicar

pytestmark = pytest.mark.db


def _uid() -> str:
    return str(uuid.uuid4())


def _um(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()[0]


# Medidas das atividades de CQ do cenário (nomes do SGBC).
MEDIDAS = ("Nome Geográfico", "Omissão", "Comissão")


class Cenario:
    def __init__(self, cur):
        self.cur = cur
        self.tema = _um(cur, "INSERT INTO mapcartacomp.tema (nome) VALUES ('teste_regras') RETURNING id")
        self.ativ = {}
        for fase in ("aquisicao", "correcao_inspecao", "envio_gcq"):
            self.ativ[fase] = _um(
                cur,
                "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome) "
                "VALUES (5, %s, %s, %s) RETURNING id",
                (self.tema, fase, f"teste {fase}"),
            )
        # CQ: uma atividade por medida.
        self.ativ_cq = {}
        for medida in MEDIDAS:
            self.ativ_cq[medida] = _um(
                cur,
                "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome, id_medidadequalidade) "
                "SELECT 5, %s, 'cq', %s, id FROM mapcartctrl.t_qua_medidadequalidade WHERE nome = %s RETURNING id",
                (self.tema, f"teste CQ {medida}", medida),
            )
        self.fluxo = _um(
            cur,
            "INSERT INTO mapcartacomp.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, 'DF', 'DF teste') "
            "RETURNING id",
            (self.tema,),
        )
        self.etapa = {}
        for ordem, (fase, conta, repetivel) in enumerate(
            [
                ("aquisicao", True, True),
                ("cq", False, True),
                ("correcao_inspecao", False, False),
                ("envio_gcq", False, True),
            ],
            start=1,  # fmt: skip
        ):
            self.etapa[fase] = _um(
                cur,
                "INSERT INTO mapcartacomp.fluxo_etapa (id_fluxo, ordem, fase, nome, conta_revisao, repetivel) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (self.fluxo, ordem, fase, f"Etapa {fase}", conta, repetivel),
            )
            for a in self.ativ_cq.values() if fase == "cq" else [self.ativ[fase]]:
                cur.execute(
                    "INSERT INTO mapcartacomp.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) VALUES (%s, %s)",
                    (self.etapa[fase], a),
                )
        folha = _um(cur, "SELECT id_articulacao_scn FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = '2534'")
        self.lote = _um(
            cur,
            "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
            "VALUES (%s, 5, %s, %s, 'DF', 'folha', %s, '2534') RETURNING id",
            (_uid(), self.tema, self.fluxo, folha),
        )
        self.fase_da_passagem = {}

    def passagem(self, fase, situacao="pendente", revisao=None, instancia=1):
        le = _um(
            self.cur,
            "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, instancia, situacao, revisao, "
            "iniciada_em) VALUES (%s, %s, %s, %s, %s, %s, CASE WHEN %s <> 'pendente' THEN clock_timestamp() END) "
            "RETURNING id",
            (_uid(), self.lote, self.etapa[fase], instancia, situacao, revisao, situacao),
        )
        self.fase_da_passagem[le] = fase
        return le

    def mudar(self, lote_etapa, situacao, resultado=None):
        self.cur.execute(
            "UPDATE mapcartacomp.lote_etapa SET situacao = %s, resultado = %s, "
            "iniciada_em = coalesce(iniciada_em, clock_timestamp()), "
            "concluida_em = CASE WHEN %s = 'concluida' THEN clock_timestamp() END WHERE id = %s",
            (situacao, resultado, situacao, lote_etapa),
        )

    def plano(self, lote_etapa, medida, ac):
        return _um(
            self.cur,
            "INSERT INTO mapcartacomp.cq_plano (uuid, id_lote_etapa, id_atividade, numero_aceitacao_ac) "
            "VALUES (%s, %s, %s, %s) RETURNING id",
            (_uid(), lote_etapa, self.ativ_cq[medida], ac),
        )

    def carga(self, lote_etapa, responsavel=None, concluido=False, concluido_em=None, plano=None, x=-44.5,
              atividade=None, geocodigo=None):  # fmt: skip
        """Carga na passagem. Sem atividade: a do plano (CQ) ou a única da etapa."""
        if atividade is None:
            if plano is not None:
                atividade = _um(self.cur, "SELECT id_atividade FROM mapcartacomp.cq_plano WHERE id = %s", (plano,))
            else:
                atividade = self.ativ[self.fase_da_passagem[lote_etapa]]
        return _um(
            self.cur,
            "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, id_cq_plano, responsavel, "
            "geom, geocodigo, concluido, concluido_em) VALUES (%s, %s, %s, %s, %s, "
            "CASE WHEN %s::text IS NULL THEN ST_Multi(ST_MakeEnvelope(%s, -20.0, %s + 0.05, -19.95, 4674)) "
            "ELSE mapcartacomp.f_grade_celula(%s) END, %s, %s, %s) RETURNING id",
            (
                _uid(),
                lote_etapa,
                atividade,
                plano,
                responsavel,
                geocodigo,
                x,
                x,
                geocodigo,
                geocodigo,
                concluido,
                concluido_em,
            ),  # fmt: skip
        )

    def amostra(self, plano, carga):
        return _um(
            self.cur,
            "INSERT INTO mapcartacomp.cq_amostra (uuid, id_cq_plano, id_carga_trabalho) VALUES (%s, %s, %s) "
            "RETURNING id",
            (_uid(), plano, carga),
        )

    def lote_estado(self):
        self.cur.execute(
            "SELECT status_nacional, revisao_atual, id_lote_etapa_atual FROM mapcartacomp.lote WHERE id = %s",
            (self.lote,),
        )
        return self.cur.fetchone()


@pytest.fixture
def cen(banco):
    aplicar(banco)
    with banco.cursor() as cur:
        yield Cenario(cur)


def _erro(cur, erro, fn, *args, **kwargs):
    """Confere que fn levanta o erro, sem perder a transação do teste."""
    cur.execute("SAVEPOINT s")
    with pytest.raises(erro):
        fn(*args, **kwargs)
    cur.execute("ROLLBACK TO SAVEPOINT s")


def test_concluir_e_desfazer_carga(cen):
    cur = cen.cur
    le = cen.passagem("aquisicao", "em_andamento")
    c = cen.carga(le)
    cur.execute("UPDATE mapcartacomp.carga_trabalho SET concluido = true WHERE id = %s RETURNING concluido_em", (c,))
    assert cur.fetchone()[0] is not None
    cur.execute("UPDATE mapcartacomp.carga_trabalho SET concluido = false WHERE id = %s RETURNING concluido_em", (c,))
    assert cur.fetchone()[0] is None
    # Conclusão feita offline: a hora informada é mantida.
    cur.execute(
        "UPDATE mapcartacomp.carga_trabalho SET concluido = true, concluido_em = '2026-01-02 10:00+00' "
        "WHERE id = %s RETURNING concluido_em = '2026-01-02 10:00+00'",
        (c,),
    )
    assert cur.fetchone()[0] is True
    # INSERT já concluído (migração/sincronização) mantém a hora; sem hora, recebe agora.
    c2 = cen.carga(le, concluido=True, concluido_em="2025-12-01 08:00+00")
    assert _um(cur, "SELECT concluido_em = '2025-12-01 08:00+00' FROM mapcartacomp.carga_trabalho WHERE id = %s", (c2,))
    c3 = cen.carga(le, concluido=True)
    assert _um(cur, "SELECT concluido_em IS NOT NULL FROM mapcartacomp.carga_trabalho WHERE id = %s", (c3,))


def test_atualizado_em_em_todo_update(cen):
    cur = cen.cur
    cur.execute(
        "UPDATE mapcartacomp.lote SET atualizado_em = '2000-01-01', atualizado_por = 'outro' WHERE id = %s "
        "RETURNING atualizado_em > '2000-01-01', atualizado_por = current_user",
        (cen.lote,),
    )
    assert cur.fetchone() == (True, True)


def test_uf_herdada_do_pai(cen):
    le = cen.passagem("aquisicao")
    c = cen.carga(le)
    assert _um(cen.cur, "SELECT uf FROM mapcartacomp.lote_etapa WHERE id = %s", (le,)) == "DF"
    assert _um(cen.cur, "SELECT uf FROM mapcartacomp.carga_trabalho WHERE id = %s", (c,)) == "DF"


def test_cq_conclui_carga_e_fecha_plano(cen):
    """Um plano por atividade (medida); cada carga sorteada tem uma amostra e conclui quando ela é avaliada."""
    cur = cen.cur
    le = cen.passagem("cq", "em_andamento")
    planos = {m: cen.plano(le, m, ac=1) for m in MEDIDAS}
    # As mesmas três células sorteadas nas três medidas: três cargas por célula, uma de cada atividade.
    cargas = {m: [cen.carga(le, plano=planos[m], x=-44.5 + i * 0.05) for i in range(3)] for m in MEDIDAS}
    amostras = {m: [cen.amostra(planos[m], c) for c in cargas[m]] for m in MEDIDAS}

    def avaliar(m, i, status):
        cur.execute("UPDATE mapcartacomp.cq_amostra SET status = %s WHERE id = %s", (status, amostras[m][i]))

    def estado(m):
        cur.execute(
            "SELECT array_agg(concluido ORDER BY id) FROM mapcartacomp.carga_trabalho WHERE id_cq_plano = %s",
            (planos[m],),
        )
        concl = cur.fetchone()[0]
        return concl, _um(cur, "SELECT resultado FROM mapcartacomp.cq_plano WHERE id = %s", (planos[m],))

    assert estado("Omissão") == ([False, False, False], "pendente")
    avaliar("Omissão", 0, 0)
    assert estado("Omissão") == ([True, False, False], "pendente")
    # Avaliar uma medida não mexe nas cargas da mesma célula nas outras medidas.
    assert estado("Comissão") == ([False, False, False], "pendente")
    assert _um(cur, "SELECT avaliado_por = current_user FROM mapcartacomp.cq_amostra WHERE id = %s",
               (amostras["Omissão"][0],))  # fmt: skip
    avaliar("Omissão", 1, 1)
    avaliar("Omissão", 2, 0)
    # Dois não conformes em Omissão com Ac = 1: reprovado.
    assert estado("Omissão") == ([True, True, True], "reprovado")
    avaliar("Omissão", 2, 1)
    assert estado("Omissão") == ([True, True, True], "aprovado")
    for i in range(3):
        avaliar("Comissão", i, 1)
    assert estado("Comissão") == ([True, True, True], "aprovado")
    # Desfazer uma avaliação reabre a carga e o plano.
    avaliar("Omissão", 1, None)
    assert estado("Omissão") == ([True, False, True], "pendente")
    assert estado("Nome Geográfico") == ([False, False, False], "pendente")
    # Etapa de CQ continua como o supervisor deixou: nada avança sozinho.
    assert _um(cur, "SELECT situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,)) == "em_andamento"


def test_carga_se_faz_uma_vez(cen, psycopg2):
    """A mesma célula não vira duas cargas da mesma atividade na mesma passagem; em outra atividade, sim."""
    cur = cen.cur
    celula = grade.celula_do_ponto(5000, -44.25, -19.75)
    aq = cen.passagem("aquisicao", "em_andamento")
    cen.carga(aq, geocodigo=celula)
    _erro(cur, psycopg2.errors.UniqueViolation, cen.carga, aq, geocodigo=celula)
    # Outra passagem (revisão seguinte) gera a célula de novo.
    cen.carga(cen.passagem("aquisicao", "pendente", instancia=2), geocodigo=celula)
    cq = cen.passagem("cq", "em_andamento")
    om, co = cen.plano(cq, "Omissão", 0), cen.plano(cq, "Comissão", 0)
    cen.carga(cq, plano=om, geocodigo=celula)
    cen.carga(cq, plano=co, geocodigo=celula)
    _erro(cur, psycopg2.errors.UniqueViolation, cen.carga, cq, plano=om, geocodigo=celula)
    # Uma carga, uma amostra.
    c = cen.carga(cq, plano=om, geocodigo=grade.celula_do_ponto(5000, -44.15, -19.75))
    cen.amostra(om, c)
    _erro(cur, psycopg2.errors.UniqueViolation, cen.amostra, om, c)


def test_atividade_da_carga_e_do_plano(cen, psycopg2):
    cur = cen.cur
    aq = cen.passagem("aquisicao", "em_andamento")
    cq = cen.passagem("cq", "em_andamento")
    # Atividade que não é da etapa da passagem: recusada na carga e no plano.
    _erro(cur, psycopg2.errors.CheckViolation, cen.carga, aq, atividade=cen.ativ_cq["Omissão"])
    _erro(cur, psycopg2.errors.CheckViolation, cen.carga, cq, atividade=cen.ativ["aquisicao"])
    _erro(cur, psycopg2.errors.CheckViolation, cen.plano, aq, "Omissão", 0)
    # Carga de CQ tem a atividade e a passagem do plano que a sorteou.
    om = cen.plano(cq, "Omissão", 0)
    _erro(cur, psycopg2.errors.ForeignKeyViolation, cen.carga, cq, plano=om, atividade=cen.ativ_cq["Comissão"])
    # Amostra só em carga do mesmo plano.
    c = cen.carga(cq, plano=cen.plano(cq, "Comissão", 0))
    _erro(cur, psycopg2.errors.ForeignKeyViolation, cen.amostra, om, c)


def test_atividade_de_cq_tem_medida_e_etapa_so_aceita_a_sua_fase(cen, psycopg2):
    cur = cen.cur

    def atividade(fase, medida):
        cur.execute(
            "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome, id_medidadequalidade) "
            "VALUES (5, %s, %s, 'x', (SELECT id FROM mapcartctrl.t_qua_medidadequalidade WHERE nome = %s))",
            (cen.tema, fase, medida),
        )

    _erro(cur, psycopg2.errors.CheckViolation, atividade, "cq", None)
    _erro(cur, psycopg2.errors.CheckViolation, atividade, "aquisicao", "Omissão")
    # Medida fora do catálogo de CQ do Feixe (Acurácia Posicional não é semeada).
    _erro(cur, psycopg2.errors.ForeignKeyViolation, atividade, "cq", "Acurácia Posicional")

    def ligar(etapa, ativ):
        cur.execute(
            "INSERT INTO mapcartacomp.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) VALUES (%s, %s)",
            (etapa, ativ),
        )

    _erro(cur, psycopg2.errors.CheckViolation, ligar, cen.etapa["cq"], cen.ativ["aquisicao"])
    outro_tema = _um(cur, "INSERT INTO mapcartacomp.tema (nome) VALUES ('teste_regras_2') RETURNING id")
    de_outro_tema = _um(
        cur,
        "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome) VALUES (5, %s, 'aquisicao', 'y') "
        "RETURNING id",
        (outro_tema,),
    )
    _erro(cur, psycopg2.errors.CheckViolation, ligar, cen.etapa["aquisicao"], de_outro_tema)


def test_status_nacional_e_revisao_seguem_o_supervisor(cen):
    assert cen.lote_estado() == ("PLANEJADA", 0, None)
    aq1 = cen.passagem("aquisicao")
    assert _um(cen.cur, "SELECT revisao FROM mapcartacomp.lote_etapa WHERE id = %s", (aq1,)) == 1
    assert cen.lote_estado() == ("PLANEJADA", 0, aq1)
    cen.mudar(aq1, "em_andamento")
    assert cen.lote_estado() == ("EM_PRODUCAO", 1, aq1)
    # Todas as cargas concluídas não mudam a etapa: o supervisor decide.
    cen.carga(aq1, concluido=True)
    assert cen.lote_estado() == ("EM_PRODUCAO", 1, aq1)
    cen.mudar(aq1, "concluida")
    cq1 = cen.passagem("cq")
    assert cen.lote_estado() == ("EM_PRODUCAO", 1, aq1)
    cen.mudar(cq1, "em_andamento")
    assert cen.lote_estado() == ("EM_CQ", 1, cq1)
    cen.mudar(cq1, "concluida")
    aq2 = cen.passagem("aquisicao", instancia=2)
    assert _um(cen.cur, "SELECT revisao FROM mapcartacomp.lote_etapa WHERE id = %s", (aq2,)) == 2
    cen.mudar(aq2, "em_andamento")
    assert cen.lote_estado() == ("EM_PRODUCAO", 2, aq2)
    cen.mudar(aq2, "concluida")
    cq2 = cen.passagem("cq", instancia=2)
    assert _um(cen.cur, "SELECT revisao FROM mapcartacomp.lote_etapa WHERE id = %s", (cq2,)) == 2
    cen.mudar(cq2, "em_andamento")
    assert cen.lote_estado() == ("EM_CQ", 2, cq2)
    cen.mudar(cq2, "concluida")
    corr = cen.passagem("correcao_inspecao", "pulada")
    assert cen.lote_estado() == ("EM_CQ", 2, cq2)
    env = cen.passagem("envio_gcq", "em_andamento")
    assert cen.lote_estado() == ("ENTREGUE_GCQ", 2, env)
    cen.mudar(env, "concluida", "devolvida")
    assert cen.lote_estado() == ("DEVOLVIDA", 2, env)
    # O supervisor volta para a correção de inspeção.
    cen.cur.execute("DELETE FROM mapcartacomp.lote_etapa WHERE id = %s", (corr,))
    corr = cen.passagem("correcao_inspecao", "em_andamento")
    assert cen.lote_estado() == ("EM_PRODUCAO", 2, corr)
    cen.mudar(corr, "concluida")
    env2 = cen.passagem("envio_gcq", "em_andamento", instancia=2)
    cen.mudar(env2, "concluida", "aprovada")
    assert cen.lote_estado() == ("CONCLUIDA", 2, env2)


def test_views_de_compatibilidade(cen):
    cur = cen.cur
    aq1 = cen.passagem("aquisicao", "concluida")
    aq2 = cen.passagem("aquisicao", "em_andamento", instancia=2)
    c1 = cen.carga(aq1, responsavel="postgres_outro")
    c2 = cen.carga(aq2, responsavel=_um(cur, "SELECT current_user"))
    cur.execute("SELECT id_carga_trabalho, folha_revisao FROM mapcartacomp.vw_carga_trabalho WHERE id_carga_trabalho "
                "IN (%s, %s)", (c1, c2))  # fmt: skip
    assert cur.fetchall() == [(c2, "2534-2")]
    cur.execute("UPDATE mapcartacomp.vw_carga_trabalho SET concluido = true WHERE id_carga_trabalho = %s", (c2,))
    assert _um(cur, "SELECT concluido_em IS NOT NULL FROM mapcartacomp.carga_trabalho WHERE id = %s", (c2,))
    cur.execute("UPDATE mapcartacomp.vw_carga_trabalho SET concluido = true WHERE id_carga_trabalho = %s", (c1,))
    assert _um(cur, "SELECT concluido FROM mapcartacomp.carga_trabalho WHERE id = %s", (c1,)) is False

    # Amostras: só a passagem de CQ mais recente aparece na vw_cq_amostra.
    eu = _um(cur, "SELECT current_user")
    cq1 = cen.passagem("cq", "concluida")
    cq2 = cen.passagem("cq", "em_andamento", instancia=2)
    a1, a2 = {}, {}
    for m in MEDIDAS:
        p1, p2 = cen.plano(cq1, m, 2), cen.plano(cq2, m, 2)
        a1[m] = cen.amostra(p1, cen.carga(cq1, responsavel=eu, plano=p1))
        a2[m] = cen.amostra(p2, cen.carga(cq2, responsavel=eu, plano=p2, x=-44.3))
    cur.execute("SELECT id_cq_amostra, elemento FROM mapcartacomp.vw_cq_amostra WHERE id_cq_amostra = ANY(%s)",
                (list(a1.values()) + list(a2.values()),))  # fmt: skip
    assert sorted(cur.fetchall()) == sorted((a, m) for m, a in a2.items())
    cur.execute("UPDATE mapcartacomp.vw_cq_amostra SET status = 0, observacao = 'x' WHERE id_cq_amostra = %s",
                (a2["Nome Geográfico"],))  # fmt: skip
    assert _um(cur, "SELECT status FROM mapcartacomp.cq_amostra WHERE id = %s", (a2["Nome Geográfico"],)) == 0
    assert _um(cur, "SELECT count(*) FROM mapcartacomp.vw_cq_amostra_all WHERE id_cq_amostra = %s",
               (a1["Nome Geográfico"],)) == 1  # fmt: skip

    # Ocorrência inserida pela view sem lote: herda lote e carga da carga do usuário que contém o ponto.
    u = _uid()
    cur.execute(
        "INSERT INTO mapcartacomp.vw_cq_inspecao (uuid, elemento, anotacao, geom) "
        "VALUES (%s, 'Nome', 'nome errado', ST_SetSRID(ST_MakePoint(-44.27, -19.97), 4674)) "
        "RETURNING id_lote, id_carga_trabalho, responsavel = current_user",
        (u,),
    )
    lote, carga, meu = cur.fetchone()
    assert lote == cen.lote and meu
    cur.execute("SELECT id_carga_trabalho FROM mapcartacomp.cq_amostra WHERE id = ANY(%s)", (list(a2.values()),))
    assert carga in {r[0] for r in cur.fetchall()}
    assert _um(cur, "SELECT uf FROM mapcartacomp.cq_inspecao WHERE uuid = %s", (u,)) == "DF"


def test_ctrl_lote(cen):
    cur = cen.cur
    aq1 = cen.passagem("aquisicao", "em_andamento")
    for i in range(4):
        cen.carga(aq1, concluido=i < 3, x=-44.5 + i * 0.05)
    cur.execute(
        "SELECT folha_revisao, status_nacional, etapa, cargas_total, cargas_concluidas, perc_concluidas "
        "FROM mapcartacomp.ctrl_lote WHERE id_lote = %s",
        (cen.lote,),
    )
    assert cur.fetchone() == ("2534-1", "EM_PRODUCAO", "Etapa aquisicao", 4, 3, 75)
    cen.mudar(aq1, "concluida")
    cq1 = cen.passagem("cq", "em_andamento")
    p = cen.plano(cq1, "Omissão", 0)
    a = cen.amostra(p, cen.carga(cq1, plano=p))
    pc = cen.plano(cq1, "Comissão", 0)
    cen.amostra(pc, cen.carga(cq1, plano=pc))
    cur.execute("UPDATE mapcartacomp.cq_amostra SET status = 0 WHERE id = %s", (a,))
    cur.execute(
        "SELECT ultimo_cq_resultado, ultimo_cq_por_elemento -> 'Omissão' ->> 'nao_conformes', "
        "ultimo_cq_por_elemento -> 'Comissão' ->> 'pendentes', etapa FROM mapcartacomp.ctrl_lote WHERE id_lote = %s",
        (cen.lote,),
    )
    assert cur.fetchone() == ("reprovado", "1", "1", "Etapa cq")


def test_carga_fora_da_folha_e_recusada(cen, psycopg2):
    """Carga de lote-folha com menos de metade da área dentro da folha é recusada; vazar um pouco é aceito."""
    cur = cen.cur
    le = cen.passagem("aquisicao", "em_andamento")
    # A 2534 vai de -44,5 a -44,0 e de -20,0 a -19,5. Célula com 60% dentro (vaza 0,02° para oeste): aceita.
    cen.carga(le, x=-44.52)
    # Célula com 20% dentro: recusada, tanto no INSERT quanto ao mover a geometria de uma carga aceita.
    cur.execute("SAVEPOINT s")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cen.carga(le, x=-44.54)
    cur.execute("ROLLBACK TO SAVEPOINT s")
    c = cen.carga(le)
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            "UPDATE mapcartacomp.carga_trabalho SET geom = ST_Multi(ST_MakeEnvelope(-45, -20, -44.95, -19.95, 4674)) "
            "WHERE id = %s",
            (c,),
        )
