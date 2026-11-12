"""B2: minhas cargas pela camada de dados (concluir, desfazer, próxima, resumo). Dentro de transações desfeitas."""

from __future__ import annotations

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import cargas as dc

from tests.db.migracoes import aplicar
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db


@pytest.fixture
def amb(banco):
    """(cenário, executor, conta conectada)."""
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        cur.execute("SELECT current_user")
        conta = cur.fetchone()[0]
        yield Cenario(cur), ExecutorPg(dcur), conta


def _recusa(ex, fn, *args):
    ex.cur.execute("SAVEPOINT s")
    with pytest.raises(ErroDados) as e:
        fn(ex, *args)
    ex.cur.execute("ROLLBACK TO SAVEPOINT s")
    return e.value


def test_concluir_minha_carga_e_progresso(amb):
    cen, ex, eu = amb
    le = cen.passagem("aquisicao", "em_andamento")
    a, _ = cen.carga(le, eu), cen.carga(le, eu, x=-44.45)
    outra = cen.carga(le, "u_outra_pessoa", x=-44.40)
    r = dc.concluir(ex, a)
    assert r["carga"]["concluido"] and r["carga"]["concluido_em"] is not None
    assert (r["progresso"]["concluidas"], r["progresso"]["total"]) == (1, 2)  # só as minhas contam
    assert r["progresso"]["folha_revisao"].startswith("2534-")
    assert dc.concluir(ex, a)["progresso"]["concluidas"] == 1  # de novo: nada muda
    assert _recusa(ex, dc.concluir, outra).status == 403
    assert _recusa(ex, dc.concluir, 999999999).status == 404


def test_passagem_encerrada_nao_aceita_conclusao(amb):
    cen, ex, eu = amb
    le = cen.passagem("aquisicao", "em_andamento")
    c = cen.carga(le, eu)
    cen.mudar(le, "concluida")
    assert "encerrada" in _recusa(ex, dc.concluir, c).mensagem


def test_desfazer_so_em_24_horas(amb):
    cen, ex, eu = amb
    le = cen.passagem("aquisicao", "em_andamento")
    c = cen.carga(le, eu)
    assert "não está concluída" in _recusa(ex, dc.desfazer, c).mensagem
    dc.concluir(ex, c)
    r = dc.desfazer(ex, c)
    assert not r["carga"]["concluido"] and r["carga"]["concluido_em"] is None
    velha = cen.carga(le, eu, concluido=True, concluido_em="2026-01-01 10:00+00", x=-44.45)
    assert "24 horas" in _recusa(ex, dc.desfazer, velha).mensagem


def test_proxima_carga_e_a_vizinha_pendente(amb):
    cen, ex, eu = amb
    le = cen.passagem("aquisicao", "em_andamento")
    feita = cen.carga(le, eu, x=-44.50)
    perto = cen.carga(le, eu, x=-44.45)
    cen.carga(le, eu, x=-44.20)  # longe
    cen.carga(le, "u_outra_pessoa", x=-44.48)  # de outra pessoa, mais perto ainda
    assert dc.proxima(ex, feita)["id"] == perto
    dc.concluir(ex, feita)
    assert dc.proxima(ex)["id"] == perto  # sem referência: a partir da última que concluí
    assert dc.proxima(ex, perto)["id"] != perto  # a selecionada não é a próxima dela mesma
    cen.mudar(le, "concluida")
    assert dc.proxima(ex) is None  # passagem encerrada não oferece carga


def test_resumo_e_lista(amb):
    cen, ex, eu = amb
    le = cen.passagem("aquisicao", "em_andamento")
    for i in range(3):
        cen.carga(le, eu, x=-44.5 + i * 0.05)
    dc.concluir(ex, dc.minhas(ex, le)[0]["id"])
    r = dc.resumo(ex)
    p = next(x for x in r["passagens"] if x["id_lote_etapa"] == le)
    assert (p["total"], p["concluidas"], p["situacao"]) == (3, 1, "em_andamento")
    assert r["pendentes"] >= 2 and r["folhas_pendentes"] >= 1 and r["concluidas"] >= 1
    assert len(dc.minhas(ex, le, concluido=False)) == 2
    assert {c["etapa"] for c in dc.minhas(ex, le)} == {"Etapa aquisicao"}
