"""A4: GRANTs gerados para as roles escolhidas pela DBA. Roda nos dois bancos, dentro de transações desfeitas.

Nesta versão o banco não tem RLS: quem tem os GRANTs vê e altera todas as UFs, e os papéis (APM, avaliador,
supervisor, gerente) são decididos pelo plugin a partir do SGBC. Usa as roles de teste de scripts/dev/roles_teste.sql,
criadas dentro da transação, e troca de usuário com SET LOCAL ROLE.
"""

from __future__ import annotations

import os
import uuid

import pytest
from scripts.db.gerar_grants import gerar, ler_roles

from tests.db.conftest import RAIZ
from tests.db.migracoes import aplicar

pytestmark = pytest.mark.db


def _um(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()[0]


@pytest.fixture
def mundo(banco):
    aplicar(banco)
    with banco.cursor() as cur:
        with open(os.path.join(RAIZ, "scripts", "dev", "roles_teste.sql"), encoding="utf-8") as f:
            cur.execute(f.read())
        cur.execute(gerar(ler_roles(["feixe_teste_grupo"])).replace("BEGIN;", "").replace("COMMIT;", ""))
        tema = _um(cur, "INSERT INTO mapcartacomp.tema (nome) VALUES ('teste_grants') RETURNING id")
        ativ = _um(
            cur,
            "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome) "
            "VALUES (5, %s, 'aquisicao', 'teste grants') RETURNING id",
            (tema,),
        )
        ativ_cq = _um(
            cur,
            "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome, id_medidadequalidade) "
            "SELECT 5, %s, 'cq', 'teste grants CQ', id FROM mapcartctrl.t_qua_medidadequalidade "
            "WHERE nome = 'Nome Geográfico' RETURNING id",
            (tema,),
        )
        dados = {"tema": tema, "ativ": ativ, "ativ_cq": ativ_cq}
        for uf, mi in (("DF", "2534"), ("GO", "2604")):
            fluxo = _um(
                cur,
                "INSERT INTO mapcartacomp.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, %s, 'f') RETURNING id",
                (tema, uf),
            )
            etapa, etapa_cq = (
                _um(
                    cur,
                    "WITH e AS (INSERT INTO mapcartacomp.fluxo_etapa (id_fluxo, ordem, fase, nome) "
                    "VALUES (%s, %s, %s, %s) RETURNING id) "
                    "INSERT INTO mapcartacomp.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) "
                    "SELECT id, %s FROM e RETURNING id_fluxo_etapa",
                    (fluxo, ordem, fase, nome, a),
                )
                for ordem, fase, nome, a in ((1, "aquisicao", "Aquisição", ativ), (2, "cq", "CQ", ativ_cq))
            )
            folha = _um(cur, "SELECT id_articulacao_scn FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = %s",
                        (mi,))  # fmt: skip
            lote = _um(
                cur,
                "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, "
                "nome) VALUES (%s, 5, %s, %s, %s, 'folha', %s, %s) RETURNING id",
                (str(uuid.uuid4()), tema, fluxo, uf, folha, mi),
            )
            le = _um(
                cur,
                "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, situacao) "
                "VALUES (%s, %s, %s, 'em_andamento') RETURNING id",
                (str(uuid.uuid4()), lote, etapa),
            )
            # Uma célula de 0,05° no canto da folha do lote.
            carga = _um(
                cur,
                "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, responsavel, geom) "
                "SELECT %s, %s, %s, %s, ST_Multi(ST_MakeEnvelope(ST_XMin(a.geom), ST_YMin(a.geom), "
                "ST_XMin(a.geom) + 0.05, ST_YMin(a.geom) + 0.05, 4674)) "
                "FROM mapcartacomp.lote l JOIN mapcartctrl.t_articulacao_scn a USING (id_articulacao_scn) "
                "WHERE l.id = %s RETURNING id",
                (str(uuid.uuid4()), le, ativ, f"feixe_teste_{uf.lower()}", lote),
            )
            dados[uf] = {"fluxo": fluxo, "lote": lote, "le": le, "carga": carga, "etapa_cq": etapa_cq}
        yield cur, dados


def _como(cur, role):
    cur.execute(f'SET LOCAL ROLE "{role}"')


def _negado(cur, psycopg2, sql, params=()):
    cur.execute("SAVEPOINT negado")
    try:
        cur.execute(sql, params)
    except psycopg2.errors.InsufficientPrivilege:
        cur.execute("ROLLBACK TO SAVEPOINT negado")
        return True
    cur.execute("RELEASE SAVEPOINT negado")
    return False


def test_gerador_recusa_nome_invalido_e_repete_nada():
    with pytest.raises(ValueError):
        ler_roles(["role_bc100ggcdf_atua", "x; DROP SCHEMA mapcartacomp"])
    assert ler_roles(["# comentário", "", "role_a", "role_a"]) == ["role_a"]


def test_quem_tem_grant_ve_e_altera_todas_as_ufs(mundo):
    cur, d = mundo
    _como(cur, "feixe_teste_df")
    cur.execute("SELECT uf FROM mapcartacomp.lote WHERE id_tema = %s ORDER BY uf", (d["tema"],))
    assert [r[0] for r in cur.fetchall()] == ["DF", "GO"]
    # O banco não separa papéis nem UFs: altera a carga de GO e cria lote livre. Quem pode o quê é do plugin.
    cur.execute("UPDATE mapcartacomp.carga_trabalho SET concluido = true WHERE id = %s", (d["GO"]["carga"],))
    assert cur.rowcount == 1
    cur.execute(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome) "
        "VALUES (%s, 5, %s, %s, 'DF', 'livre', 'LIVRE_DF')",
        (str(uuid.uuid4()), d["tema"], d["DF"]["fluxo"]),
    )
    assert cur.rowcount == 1
    assert _um(cur, "SELECT count(*) FROM mapcartacomp.ctrl_lote WHERE id_tema = %s", (d["tema"],)) == 3


def test_configuracao_fixa_e_so_leitura(mundo, psycopg2):
    cur, _ = mundo
    _como(cur, "feixe_teste_df")
    assert _negado(cur, psycopg2, "UPDATE mapcartacomp.fase SET nome = 'x' WHERE codigo = 'cq'")
    assert _negado(cur, psycopg2, "DELETE FROM mapcartacomp.schema_version")


def test_quem_nao_tem_grant_nao_le(mundo, psycopg2):
    cur, _ = mundo
    _como(cur, "feixe_teste_fora")
    assert _negado(cur, psycopg2, "SELECT count(*) FROM mapcartacomp.carga_trabalho")


def test_avaliacao_recalcula_plano(mundo):
    """As derivações rodam como dono do schema: a avaliação feita por um usuário fecha a carga e o plano."""
    cur, d = mundo
    le = _um(
        cur,
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, situacao) "
        "VALUES (%s, %s, %s, 'em_andamento') RETURNING id",
        (str(uuid.uuid4()), d["DF"]["lote"], d["DF"]["etapa_cq"]),
    )
    plano = _um(
        cur,
        "INSERT INTO mapcartacomp.cq_plano (uuid, id_lote_etapa, id_atividade, numero_aceitacao_ac) "
        "VALUES (%s, %s, %s, 0) RETURNING id",
        (str(uuid.uuid4()), le, d["ativ_cq"]),
    )
    carga = _um(
        cur,
        "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, id_cq_plano, responsavel, geom) "
        "SELECT %s, %s, %s, %s, 'feixe_teste_df', geom FROM mapcartacomp.carga_trabalho WHERE id = %s RETURNING id",
        (str(uuid.uuid4()), le, d["ativ_cq"], plano, d["DF"]["carga"]),
    )
    amostra = _um(
        cur,
        "INSERT INTO mapcartacomp.cq_amostra (uuid, id_cq_plano, id_carga_trabalho) VALUES (%s, %s, %s) RETURNING id",
        (str(uuid.uuid4()), plano, carga),
    )
    _como(cur, "feixe_teste_df")
    cur.execute("UPDATE mapcartacomp.vw_cq_amostra SET status = 1 WHERE id_cq_amostra = %s", (amostra,))
    assert cur.rowcount == 1
    assert _um(cur, "SELECT resultado FROM mapcartacomp.cq_plano WHERE id = %s", (plano,)) == "aprovado"
    assert _um(cur, "SELECT concluido FROM mapcartacomp.carga_trabalho WHERE id = %s", (carga,)) is True
