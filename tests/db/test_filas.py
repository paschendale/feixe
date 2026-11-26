"""B8: fila de folhas por pessoa, pela camada de dados. A pessoa da fila é a própria conta conectada (current_user),
cadastrada no SGBC dentro da transação (desfeita). Concluir é da execução, no workspace (C3); aqui a carga é concluída
por UPDATE e a fila anda por `filas.puxar`, como no push do workspace."""

from __future__ import annotations

import uuid

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
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
        cur.execute("SELECT coalesce(max(id), 0) FROM mapcartacomp.fila_folha")
        _fila.base = cur.fetchone()[0]
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


def _fila(ex, chave="itens", passagens=None):
    """Itens da fila do DF criados pelo teste (o banco de dev pode ter filas de verdade)."""
    novos = [i for i in dfi.listar(ex, "DF")[chave] if i["id"] > _fila.base]
    return [i for i in novos if passagens is None or i.get("id_lote_etapa", 0) in passagens]


def _minhas(ex, le, eu):
    sql = "SELECT id FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s AND responsavel = %s ORDER BY id"
    return [r["id"] for r in ex.todos(sql, (le, eu))]


def _concluir(ex, id_carga, eu):
    """Conclui a carga e, como depois de cada conclusão, deixa a fila andar: o que `puxar` atribuiu, ou None."""
    ex.executar("UPDATE mapcartacomp.carga_trabalho SET concluido = true WHERE id = %s", (id_carga,))
    return dfi.puxar(ex, eu)


def _desfazer(ex, id_carga):
    ex.executar("UPDATE mapcartacomp.carga_trabalho SET concluido = false WHERE id = %s", (id_carga,))


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
    assert "não encontrado" in _recusa(ex, dfi.adicionar, "GO", eu, a)
    dfi.reordenar(ex, "DF", eu, [ib, ia])  # B passa na frente
    assert "mudou" in _recusa(ex, dfi.reordenar, "DF", eu, [ib])

    assert _concluir(ex, minhas[0], eu) is None  # ainda tenho pendente: nada muda
    r = _concluir(ex, minhas[1], eu)
    assert (r["id_lote_etapa"], r["atribuidas"]) == (b, 2)
    assert _donos(ex, b) == sorted([eu, eu, "t_apm_b"]) and _donos(ex, a) == ["-", "-"]
    assert [i["id"] for i in _fila(ex)] == [ia]
    assert [x["id"] for x in _fila(ex, "recentes")] == [ib]

    # Desfazer não desatribui, e concluir de novo com B ainda pendente não puxa A.
    _desfazer(ex, minhas[1])
    assert _concluir(ex, minhas[1], eu) is None and _donos(ex, b).count(eu) == 2

    # Item sem nada a atribuir é pulado e fica na fila; acabou B, vem A; acabou a fila, nada.
    c = _folha_livre(cen, "fila C")
    cen.carga(c, "t_apm_b", x=-44.5)
    ic = dfi.adicionar(ex, "DF", eu, c)["id"]
    dfi.reordenar(ex, "DF", eu, [ic, ia])
    ids_b = _minhas(ex, b, eu)
    _concluir(ex, ids_b[0], eu)
    assert _concluir(ex, ids_b[1], eu)["id_lote_etapa"] == a
    assert [i["id"] for i in _fila(ex)] == [ic]
    assert [_concluir(ex, i, eu) for i in _minhas(ex, a, eu)] == [None, None]  # C não tem o que atribuir

    # Quem está sem carga recebe já: não vai concluir nada para a fila andar.
    _conta(cen.cur, "t_apm_c")
    d = _folha_livre(cen, "fila D")
    cen.carga(d, x=-44.5)
    assert dfi.adicionar(ex, "DF", "t_apm_c", d)["atribuida"]["atribuidas"] == 1 and _donos(ex, d) == ["t_apm_c"]

    dfi.remover(ex, "DF", ic)
    assert _fila(ex) == []
    assert "não está mais" in _recusa(ex, dfi.remover, "DF", ic)


def test_passar_pendentes_segue_a_fila(amb):
    """Equipe › Passar pendentes: uma folha por pessoa. Quem recebe e já trabalha numa das folhas fica com ela na
    hora; as outras entram na fila dele e a primeira só vem quando ele ficar sem carga. A fila de quem passou não
    anda; as concluídas ficam com quem fez."""
    cen, ex, eu = amb
    _conta(cen.cur, "t_apm_c")
    a, b, c = (_folha_livre(cen, f"passar {n}") for n in "ABC")
    for le in (a, b, c):
        cen.carga(le, "t_apm_b", x=-44.5)
        cen.carga(le, "t_apm_b", x=-44.45)
    cen.carga(a, "t_apm_b", concluido=True, concluido_em="2026-01-01", x=-44.4)
    cen.carga(b, eu, x=-44.4)  # eu já trabalho na B
    d = _folha_livre(cen, "passar D")
    cen.carga(d, x=-44.5)
    dfi.adicionar(ex, "DF", "t_apm_b", d)  # fila de quem passa: não anda

    assert "outra pessoa" in _recusa(ex, dfi.passar_pendentes, "DF", eu, eu)
    r = dfi.passar_pendentes(ex, "DF", "t_apm_b", eu)
    assert r["agora"] == 2 and r["recebida"] is None  # só a B, onde eu já trabalho
    assert [f["id_lote_etapa"] for f in r["na_fila"]] == [a, c]
    assert _donos(ex, b) == [eu, eu, eu]
    assert _donos(ex, a) == ["-", "-", "t_apm_b"] and _donos(ex, c) == ["-", "-"] and _donos(ex, d) == ["-"]
    fila = [(i["responsavel"], i["id_lote_etapa"]) for i in _fila(ex)]
    assert sorted(fila) == sorted([(eu, a), (eu, c), ("t_apm_b", d)])

    # Quem está sem carga recebe a primeira folha na hora, e o resto fica na fila.
    r = dfi.passar_pendentes(ex, "DF", eu, "t_apm_c")
    assert r["recebida"]["id_lote_etapa"] == b and r["agora"] == 3 and r["na_fila"] == []
    assert _donos(ex, b) == ["t_apm_c"] * 3
    assert "não tem cargas pendentes" in _recusa(ex, dfi.passar_pendentes, "DF", eu, "t_apm_c")

    # Para ninguém: as cargas ficam a atribuir.
    r = dfi.passar_pendentes(ex, "DF", "t_apm_c", None)
    assert r["liberadas"] == 3 and _donos(ex, b) == ["-", "-", "-"]
