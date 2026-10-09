"""A4: GRANTs gerados para as roles de grupo e RLS por UF. Roda nos dois bancos, dentro de transações desfeitas.

Usa as roles de teste de scripts/dev/roles_teste.sql (role_bc100ggcdf_* e role_bc100ggcgo_*), criadas dentro da
transação, e troca de usuário com SET LOCAL ROLE.
"""

from __future__ import annotations

import os
import uuid

import pytest
from scripts.db.gerar_grants import gerar, ler_roles

from tests.db.conftest import RAIZ
from tests.db.migracoes import aplicar

pytestmark = pytest.mark.db

ROLES = ["role_bc100ggcdf_atua", "role_bc100ggcdf_sup", "role_bc100ggcgo_atua", "role_bc100ggcgo_sup"]


def _um(cur, sql, params=()):
    cur.execute(sql, params)
    return cur.fetchone()[0]


@pytest.fixture
def mundo(banco):
    aplicar(banco)
    with banco.cursor() as cur:
        with open(os.path.join(RAIZ, "scripts", "dev", "roles_teste.sql"), encoding="utf-8") as f:
            cur.execute(f.read())
        cur.execute(gerar(ler_roles(ROLES)).replace("BEGIN;", "").replace("COMMIT;", ""))
        tema = _um(cur, "INSERT INTO mapcartacomp.tema (nome) VALUES ('teste_grants') RETURNING id")
        ativ = _um(
            cur,
            "INSERT INTO mapcartacomp.atividade (cod_projeto, id_tema, fase, nome) "
            "VALUES (5, %s, 'aquisicao', 'teste grants') RETURNING id",
            (tema,),
        )
        dados = {"tema": tema}
        for uf, mi in (("DF", "2534"), ("GO", "2604")):
            fluxo = _um(
                cur,
                "INSERT INTO mapcartacomp.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, %s, 'f') RETURNING id",
                (tema, uf),
            )
            etapa = _um(
                cur,
                "INSERT INTO mapcartacomp.fluxo_etapa (id_fluxo, ordem, id_atividade, nome) "
                "VALUES (%s, 1, %s, 'Aquisição') RETURNING id",
                (fluxo, ativ),
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
            dados[uf] = {"fluxo": fluxo, "lote": lote, "le": le}
        cargas = {}
        for dono, uf in (("feixe_teste_apm_df", "DF"), ("feixe_teste_apm2_df", "DF"), ("feixe_teste_apm_go", "GO")):
            cargas[dono] = _um(
                cur,
                "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, responsavel, geom) "
                "VALUES (%s, %s, %s, ST_Multi(ST_MakeEnvelope(-44.5, -20, -44.45, -19.95, 4674))) RETURNING id",
                (str(uuid.uuid4()), dados[uf]["le"], dono),
            )
        dados["cargas"] = cargas
        yield cur, dados


def _como(cur, role):
    cur.execute(f'SET LOCAL ROLE "{role}"')


def _volta(cur):
    cur.execute("RESET ROLE")


def _negado(cur, psycopg2, sql, params=()):
    cur.execute("SAVEPOINT negado")
    try:
        cur.execute(sql, params)
    except psycopg2.errors.InsufficientPrivilege:
        cur.execute("ROLLBACK TO SAVEPOINT negado")
        return True
    cur.execute("RELEASE SAVEPOINT negado")
    return False


def _lotes_visiveis(cur, dados):
    cur.execute("SELECT uf FROM mapcartacomp.lote WHERE id_tema = %s ORDER BY uf", (dados["tema"],))
    return [r[0] for r in cur.fetchall()]


def test_gerador_recusa_role_fora_do_padrao():
    with pytest.raises(ValueError):
        ler_roles(["role_bc100ggcdf_atua", "feixe_apm"])
    assert ler_roles(["# comentário", "", "role_bc100grj_sup", "role_bc100grj_sup"]) == ["role_bc100grj_sup"]
    assert "GRANT INSERT" not in gerar(["role_bc100ggcdf_sup"], espelho=True)


def test_atua_so_mexe_no_que_e_seu(mundo, psycopg2):
    cur, d = mundo
    _como(cur, "feixe_teste_apm_df")
    assert _lotes_visiveis(cur, d) == ["DF"]
    cur.execute("SELECT count(*) FROM mapcartacomp.carga_trabalho WHERE id = ANY(%s)", (list(d["cargas"].values()),))
    assert cur.fetchone()[0] == 2
    # Não cria lote.
    assert _negado(
        cur,
        psycopg2,
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome) "
        "VALUES (%s, 5, %s, %s, 'DF', 'livre', 'x')",
        (str(uuid.uuid4()), d["tema"], d["DF"]["fluxo"]),
    )
    # Conclui a própria carga; a do colega não muda (RLS esconde a linha da escrita).
    cur.execute(
        "UPDATE mapcartacomp.carga_trabalho SET concluido = true WHERE id = %s", (d["cargas"]["feixe_teste_apm_df"],)
    )
    assert cur.rowcount == 1
    cur.execute("UPDATE mapcartacomp.carga_trabalho SET concluido = true WHERE id = %s",
                (d["cargas"]["feixe_teste_apm2_df"],))  # fmt: skip
    assert cur.rowcount == 0
    # Não se auto-atribui nem repassa carga: responsavel não está entre as colunas que _atua altera.
    assert _negado(cur, psycopg2, "UPDATE mapcartacomp.carga_trabalho SET responsavel = current_user WHERE id = %s",
                   (d["cargas"]["feixe_teste_apm2_df"],))  # fmt: skip
    # Mudar a etapa é do supervisor.
    assert _negado(cur, psycopg2, "UPDATE mapcartacomp.lote_etapa SET situacao = 'concluida' WHERE id = %s",
                   (d["DF"]["le"],))  # fmt: skip
    _volta(cur)
    assert _um(cur, "SELECT concluido FROM mapcartacomp.carga_trabalho WHERE id = %s",
               (d["cargas"]["feixe_teste_apm2_df"],)) is False  # fmt: skip


def test_sup_planeja_so_na_propria_uf(mundo, psycopg2):
    cur, d = mundo
    _como(cur, "feixe_teste_sup_df")
    assert _lotes_visiveis(cur, d) == ["DF"]
    cur.execute(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome) "
        "VALUES (%s, 5, %s, %s, 'DF', 'livre', 'LIVRE_DF')",
        (str(uuid.uuid4()), d["tema"], d["DF"]["fluxo"]),
    )
    assert cur.rowcount == 1
    # Lote em outra UF: o RLS recusa.
    assert _negado(
        cur,
        psycopg2,
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome) "
        "VALUES (%s, 5, %s, %s, 'GO', 'livre', 'LIVRE_GO')",
        (str(uuid.uuid4()), d["tema"], d["GO"]["fluxo"]),
    )
    # Reatribui carga de outro APM da UF e avança a etapa (ação explícita do supervisor).
    cur.execute("UPDATE mapcartacomp.carga_trabalho SET responsavel = NULL WHERE id = %s",
                (d["cargas"]["feixe_teste_apm2_df"],))  # fmt: skip
    assert cur.rowcount == 1
    cur.execute("UPDATE mapcartacomp.lote_etapa SET situacao = 'concluida' WHERE id = %s", (d["DF"]["le"],))
    assert cur.rowcount == 1
    # Carga de GO: invisível, nada muda.
    cur.execute("UPDATE mapcartacomp.carga_trabalho SET responsavel = NULL WHERE id = %s",
                (d["cargas"]["feixe_teste_apm_go"],))  # fmt: skip
    assert cur.rowcount == 0


def test_cada_uf_ve_so_a_sua_e_o_gerente_ve_todas(mundo):
    cur, d = mundo
    _como(cur, "feixe_teste_apm_go")
    assert _lotes_visiveis(cur, d) == ["GO"]
    _volta(cur)
    # Gerente: papel só do Feixe, em usuario_feixe (que referencia uma conta real de t_usuario).
    conta = _um(cur, "SELECT nom_contausuario FROM mapcartctrl.t_usuario ORDER BY cod_usuario LIMIT 1")
    if not _um(cur, "SELECT count(*) FROM pg_roles WHERE rolname = %s", (conta,)):
        cur.execute(f'CREATE ROLE "{conta}" NOLOGIN')
    cur.execute(f'GRANT role_bc100ggcgo_atua TO "{conta}"')
    cur.execute("INSERT INTO mapcartacomp.usuario_feixe (usuario, gerente) VALUES (%s, true)", (conta,))
    _como(cur, conta)
    assert _lotes_visiveis(cur, d) == ["DF", "GO"]


def test_avaliacao_pelo_avaliador_recalcula_plano(mundo):
    """As derivações rodam como dono: o avaliador avalia e o plano (que ele não pode alterar) é recalculado."""
    cur, d = mundo
    carga = d["cargas"]["feixe_teste_apm_df"]
    plano = _um(
        cur,
        "INSERT INTO mapcartacomp.cq_plano (uuid, id_lote_etapa, elementos, numero_aceitacao_ac) "
        "VALUES (%s, %s, ARRAY['Nome'], 0) RETURNING id",
        (str(uuid.uuid4()), d["DF"]["le"]),
    )
    amostra = _um(
        cur,
        "INSERT INTO mapcartacomp.cq_amostra (uuid, id_cq_plano, id_carga_trabalho, elemento) "
        "VALUES (%s, %s, %s, 'Nome') RETURNING id",
        (str(uuid.uuid4()), plano, carga),
    )
    _como(cur, "feixe_teste_apm_df")
    cur.execute("UPDATE mapcartacomp.cq_amostra SET status = 1 WHERE id = %s", (amostra,))
    assert cur.rowcount == 1
    assert _um(cur, "SELECT resultado FROM mapcartacomp.cq_plano WHERE id = %s", (plano,)) == "aprovado"
    assert _um(cur, "SELECT concluido FROM mapcartacomp.carga_trabalho WHERE id = %s", (carga,)) is True
