"""B5: equipe da UF e atribuição de cargas, pela camada de dados. Contas de teste criadas na transação (desfeita)."""

from __future__ import annotations

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import cargas as dc

from tests.db.migracoes import aplicar
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db


def _conta(cur, conta, lotacao="DF", perfil="O", ativa=True):
    cur.execute("SET LOCAL session_replication_role = replica")  # sem a sincronização do SGBC com as GGCs
    cur.execute(
        "INSERT INTO mapcartctrl.t_usuario (nom_contausuario, nom_usuario, dsc_lotacao, ind_contaativa) "
        "VALUES (%s, %s, %s, %s) RETURNING cod_usuario",
        (conta, f"Teste {conta}", lotacao, ativa),
    )
    cod = cur.fetchone()[0]
    if perfil:
        cur.execute(
            "INSERT INTO mapcartctrl.t_prd_perfil_usuarioprojeto (cd_usuario, cd_projeto, cd_perfil) "
            "VALUES (%s, 5, %s)",
            (cod, perfil),
        )
    cur.execute("SET LOCAL session_replication_role = origin")


@pytest.fixture
def amb(banco):
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        cen = Cenario(cur)
        _conta(cur, "t_apm_a")
        _conta(cur, "t_apm_b", perfil="V")
        _conta(cur, "t_go", lotacao="GO")
        _conta(cur, "t_inativo", ativa=False)
        _conta(cur, "t_consulta", perfil="C")
        yield cen, ExecutorPg(dcur)


def _recusa(ex, fn, *args, **kw):
    ex.cur.execute("SAVEPOINT s")
    with pytest.raises(ErroDados) as e:
        fn(ex, *args, **kw)
    ex.cur.execute("ROLLBACK TO SAVEPOINT s")
    return e.value


def _resp(ex, ids):
    return [r["responsavel"] for r in ex.todos(
        "SELECT responsavel FROM mapcartacomp.carga_trabalho WHERE id = ANY(%s) ORDER BY id", (ids,))]  # fmt: skip


def test_equipe_da_uf_so_com_contas_aptas(amb):
    _, ex = amb
    contas = {e["conta"] for e in dc.equipe(ex, "DF", 5)}
    assert {"t_apm_a", "t_apm_b"} <= contas
    assert not contas & {"t_go", "t_inativo", "t_consulta"}


def test_atribuir_folha_inteira_e_trocar_no_meio(amb):
    cen, ex = amb
    le = cen.passagem("aquisicao", "em_andamento")
    ids = [cen.carga(le, x=-44.5 + i * 0.05) for i in range(4)]
    feita = cen.carga(le, "t_apm_b", concluido=True, x=-44.3)
    r = dc.atribuir(ex, "DF", "t_apm_a", lote_etapas=[le])
    assert (r["atribuidas"], r["fora"]) == (4, 1)  # a concluída fica com quem a fez
    assert _resp(ex, ids + [feita]) == ["t_apm_a"] * 4 + ["t_apm_b"]
    # Troca no meio: duas passam para b; depois as que ainda são de a voltam para disponível.
    dc.atribuir(ex, "DF", "t_apm_b", ids=ids[:2])
    r = dc.atribuir(ex, "DF", None, lote_etapas=[le], de="t_apm_a")
    assert r["atribuidas"] == 2 and _resp(ex, ids) == ["t_apm_b", "t_apm_b", None, None]
    r = dc.atribuir(ex, "DF", "t_apm_a", lote_etapas=[le], so_disponiveis=True)
    assert r["atribuidas"] == 2 and _resp(ex, ids) == ["t_apm_b", "t_apm_b", "t_apm_a", "t_apm_a"]


def test_recusas(amb):
    cen, ex = amb
    le = cen.passagem("aquisicao", "em_andamento")
    c = cen.carga(le)
    for conta in ("t_go", "t_inativo", "t_consulta", "ninguem"):
        assert "não pode receber" in _recusa(ex, dc.atribuir, "DF", conta, ids=[c]).mensagem
    assert _recusa(ex, dc.atribuir, "DF", "t_apm_a").status == 400
    assert dc.atribuir(ex, "GO", "t_apm_a", ids=[c])["atribuidas"] == 0  # carga de outra UF não muda
    cen.mudar(le, "concluida")
    assert dc.atribuir(ex, "DF", "t_apm_a", ids=[c])["atribuidas"] == 0  # etapa encerrada não muda
