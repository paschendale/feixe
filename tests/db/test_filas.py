"""B8: fila de folhas por pessoa, pela camada de dados. A pessoa da fila é a própria conta conectada (current_user),
cadastrada no SGBC dentro da transação (desfeita), para o concluir rodar de ponta a ponta."""

from __future__ import annotations

import uuid

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import cargas as dc
from feixe.core.dados import filas as dfi

from tests.db.migracoes import aplicar
from tests.db.test_atribuir import _conta
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db


def _elegivel(cur, conta):
    """A conta conectada como executora do DF no BC100: cadastra no SGBC ou acerta a que já existe."""
    cur.execute("SELECT 1 FROM mapcartctrl.t_usuario WHERE nom_contausuario = %s", (conta,))
    if not cur.fetchone():
        _conta(cur, conta)
        return
    cur.execute("SET LOCAL session_replication_role = replica")
    cur.execute(
        "UPDATE mapcartctrl.t_usuario SET dsc_lotacao = 'DF', ind_contaativa = true, ind_contasistema = false, "
        "ind_contasuper = false WHERE nom_contausuario = %s RETURNING cod_usuario",
        (conta,),
    )
    cod = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO mapcartctrl.t_prd_perfil_usuarioprojeto (cd_usuario, cd_projeto, cd_perfil) "
        "SELECT %s, 5, 'O' WHERE NOT EXISTS (SELECT 1 FROM mapcartctrl.t_prd_perfil_usuarioprojeto "
        "WHERE cd_usuario = %s AND cd_projeto = 5 AND cd_perfil = 'O')",
        (cod, cod),
    )
    cur.execute("SET LOCAL session_replication_role = origin")


@pytest.fixture
def amb(banco):
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        cen = Cenario(cur)
        cur.execute("SELECT current_user")
        eu = cur.fetchone()[0]
        _elegivel(cur, eu)
        _conta(cur, "t_apm_b")
        yield cen, ExecutorPg(dcur), eu


def _folha_livre(cen, nome):
    """Outra folha no mesmo fluxo (lote livre sobre a 2534, onde as cargas do cenário caem), já em aquisição."""
    cen.cur.execute(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome, geom) "
        "VALUES (%s, 5, %s, %s, 'DF', 'livre', %s, ST_Multi(ST_MakeEnvelope(-45, -20.5, -44, -19.5, 4674))) "
        "RETURNING id",
        (str(uuid.uuid4()), cen.tema, cen.fluxo, nome),
    )
    lote = cen.cur.fetchone()[0]
    cen.cur.execute(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, situacao, iniciada_em) "
        "VALUES (%s, %s, %s, 'em_andamento', now()) RETURNING id",
        (str(uuid.uuid4()), lote, cen.etapa["aquisicao"]),
    )
    le = cen.cur.fetchone()[0]
    cen.fase_da_passagem[le] = "aquisicao"
    return le


def _donos(ex, le):
    return sorted(
        (r["responsavel"] or "-")
        for r in ex.todos("SELECT responsavel FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s", (le,))
    )


def _minhas(ex, le, eu):
    sql = "SELECT id FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s AND responsavel = %s ORDER BY id"
    return [r["id"] for r in ex.todos(sql, (le, eu))]


def _recusa(ex, fn, *args):
    ex.cur.execute("SAVEPOINT s")
    with pytest.raises(ErroDados) as e:
        fn(ex, *args)
    ex.cur.execute("ROLLBACK TO SAVEPOINT s")
    return e.value.mensagem


def test_fila_passa_a_proxima_folha_ao_concluir(amb):
    cen, ex, eu = amb
    atual = cen.passagem("aquisicao", "em_andamento")
    minhas = [cen.carga(atual, eu, x=-44.5 + i * 0.05) for i in range(2)]
    a = _folha_livre(cen, "fila A")
    b = _folha_livre(cen, "fila B")
    for le in (a, b):
        cen.carga(le, x=-44.5)
        cen.carga(le, x=-44.45)
    cen.carga(b, "t_apm_b", x=-44.4)  # já tem dono: a fila não tira

    ia = dfi.adicionar(ex, "DF", eu, a)["id"]  # tenho pendente: só entra na fila
    ib = dfi.adicionar(ex, "DF", eu, b)["id"]
    assert "já está na fila" in _recusa(ex, dfi.adicionar, "DF", "t_apm_b", a)
    assert "não pode receber" in _recusa(ex, dfi.adicionar, "DF", "ninguem_no_sgbc", a)
    assert "não encontrada" in _recusa(ex, dfi.adicionar, "GO", eu, a)
    dfi.reordenar(ex, "DF", eu, [ib, ia])  # B passa na frente
    assert "mudou" in _recusa(ex, dfi.reordenar, "DF", eu, [ib])

    assert dc.concluir(ex, minhas[0])["fila"] is None  # ainda tenho pendente: nada muda
    r = dc.concluir(ex, minhas[1])["fila"]
    assert (r["id_lote_etapa"], r["atribuidas"]) == (b, 2)
    assert _donos(ex, b) == sorted([eu, eu, "t_apm_b"]) and _donos(ex, a) == ["-", "-"]
    assert [i["id"] for i in dfi.listar(ex, "DF")["itens"]] == [ia]
    assert [x["id"] for x in dfi.listar(ex, "DF")["recentes"]] == [ib]

    # Desfazer não desatribui, e concluir de novo com B ainda pendente não puxa A.
    dc.desfazer(ex, minhas[1])
    assert dc.concluir(ex, minhas[1])["fila"] is None and _donos(ex, b).count(eu) == 2

    # Item sem nada a atribuir é pulado e fica na fila; acabou B, vem A; acabou a fila, nada.
    c = _folha_livre(cen, "fila C")
    cen.carga(c, "t_apm_b", x=-44.5)
    ic = dfi.adicionar(ex, "DF", eu, c)["id"]
    dfi.reordenar(ex, "DF", eu, [ic, ia])
    ids_b = _minhas(ex, b, eu)
    dc.concluir(ex, ids_b[0])
    assert dc.concluir(ex, ids_b[1])["fila"]["id_lote_etapa"] == a
    assert [i["id"] for i in dfi.listar(ex, "DF")["itens"]] == [ic]
    assert [dc.concluir(ex, i)["fila"] for i in _minhas(ex, a, eu)] == [None, None]  # C não tem o que atribuir

    # Quem está sem carga recebe já: não vai concluir nada para a fila andar.
    _conta(cen.cur, "t_apm_c")
    d = _folha_livre(cen, "fila D")
    cen.carga(d, x=-44.5)
    assert dfi.adicionar(ex, "DF", "t_apm_c", d)["atribuida"]["atribuidas"] == 1 and _donos(ex, d) == ["t_apm_c"]

    dfi.remover(ex, "DF", ic)
    assert dfi.listar(ex, "DF")["itens"] == []
    assert "não está mais" in _recusa(ex, dfi.remover, "DF", ic)
