"""C2: pull da CCAR para o workspace, contra o banco de dev (marcador `db`).

O pull roda como em produção: cada pull numa transação nova, REPEATABLE READ READ ONLY. Por isso o cenário é gravado
de verdade na CCAR de dev (cada mudança na sua transação, com o seu `now()`), com nomes que não colidem com os testes
que rodam dentro de transações desfeitas, e apagado no fim. A pessoa do escopo é a conta do workspace (`t_c2_apm`,
passada ao pull como `usuario`): em produção é o `current_user`, e `Sincronizacao` confere que os dois batem.

A compatibilidade das consultas com o 9.6 é provada à parte, no banco da GGC, com as migrações e o cenário aplicados
dentro de uma transação desfeita.
"""

from __future__ import annotations

import uuid

import pytest
from feixe.core.dados import ExecutorPg
from feixe.core.dados import cargas as dc
from feixe.core.dados.local import cargas as lc
from feixe.sync import pull
from feixe.sync.workspace import Workspace, iso_exato

from tests.db.conftest import url

pytestmark = pytest.mark.db
psycopg2 = pytest.importorskip("psycopg2")
extras = pytest.importorskip("psycopg2.extras")

EU = "t_c2_apm"
OUTRO = "t_c2_outro"
S = "mapcartacomp"


def _uid() -> str:
    return str(uuid.uuid4())


def _puxar(conn, ws, **kw):
    with conn, conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return pull.puxar(ws, ExecutorPg(cur), **kw)


class Cenario:
    """Tema, atividade e fluxo próprios, e dois lotes livres no DF (cada `executar` é uma transação confirmada):

    - passagem A, aquisição em andamento: três cargas minhas e uma de outra pessoa;
    - passagem B, pendente, na minha fila: duas cargas sem responsável;
    - passagem C, pendente, fora da fila: uma carga sem responsável (fora do meu escopo)."""

    def __init__(self, conn):
        self.conn = conn
        tag = uuid.uuid4().hex[:8]
        self.tema = self.um(f"INSERT INTO {S}.tema (nome) VALUES (%s) RETURNING id", (f"teste_pull_{tag}",))
        self.ativ = self.um(
            f"INSERT INTO {S}.atividade (cod_projeto, id_tema, fase, nome) VALUES (5, %s, 'aquisicao', %s) "
            "RETURNING id",
            (self.tema, f"teste pull {tag}"),
        )
        self.fluxo = self.um(
            f"INSERT INTO {S}.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, 'DF', %s) RETURNING id",
            (self.tema, f"DF teste pull {tag}"),
        )
        self.etapa = self.um(
            f"INSERT INTO {S}.fluxo_etapa (id_fluxo, ordem, fase, nome, conta_revisao, repetivel) "
            "VALUES (%s, 1, 'aquisicao', 'Aquisição', true, true) RETURNING id",
            (self.fluxo,),
        )
        self.executar(
            f"INSERT INTO {S}.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) VALUES (%s, %s)",
            (self.etapa, self.ativ),
        )
        self.lotes = []
        self.a = self.passagem("A", "em_andamento")
        self.b = self.passagem("B", "pendente")
        self.c = self.passagem("C", "pendente")
        self.minhas = [self.carga(self.a, EU, x) for x in (-44.9, -44.8, -44.7)]
        self.dele = self.carga(self.a, OUTRO, -44.6)
        self.livres_b = [self.carga(self.b, None, x) for x in (-44.9, -44.8)]
        self.livre_c = self.carga(self.c, None, -44.9)
        self.fila_b = self.fila(self.b, EU, 1)

    def executar(self, sql, params=()):
        with self.conn, self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0] if cur.description else None

    um = executar

    def passagem(self, nome, situacao):
        lote = self.um(
            f"INSERT INTO {S}.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome, geom) VALUES "
            "(%s, 5, %s, %s, 'DF', 'livre', %s, ST_Multi(ST_MakeEnvelope(-45, -20.5, -44, -19.5, 4674))) RETURNING id",
            (_uid(), self.tema, self.fluxo, f"T{nome}"),
        )
        self.lotes.append(lote)
        return self.um(
            f"INSERT INTO {S}.lote_etapa (uuid, id_lote, id_fluxo_etapa, situacao, iniciada_em) VALUES "
            "(%s, %s, %s, %s, CASE WHEN %s = 'pendente' THEN NULL ELSE now() END) RETURNING id",
            (_uid(), lote, self.etapa, situacao, situacao),
        )

    def carga(self, le, resp, x):
        return self.um(
            f"INSERT INTO {S}.carga_trabalho (uuid, id_lote_etapa, id_atividade, responsavel, geom) VALUES "
            "(%s, %s, %s, %s, ST_Multi(ST_MakeEnvelope(%s, -20.0, %s + 0.05, -19.95, 4674))) RETURNING id",
            (_uid(), le, self.ativ, resp, x, x),
        )

    def fila(self, le, resp, ordem):
        return self.um(
            f"INSERT INTO {S}.fila_folha (uuid, id_lote_etapa, responsavel, ordem) VALUES (%s, %s, %s, %s) "
            "RETURNING id",
            (_uid(), le, resp, ordem),
        )

    def limpar(self):
        for lote in self.lotes:
            self.executar(f"DELETE FROM {S}.lote WHERE id = %s", (lote,))
        self.executar(f"DELETE FROM {S}.fluxo WHERE id = %s", (self.fluxo,))
        self.executar(f"DELETE FROM {S}.atividade WHERE id = %s", (self.ativ,))
        self.executar(f"DELETE FROM {S}.tema WHERE id = %s", (self.tema,))


@pytest.fixture
def ccar():
    conn = psycopg2.connect(url("FEIXE_CCAR"))
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def cen(ccar):
    c = Cenario(ccar)
    try:
        yield c
    finally:
        c.limpar()


@pytest.fixture
def ws(tmp_path):
    w = Workspace.abrir("dev", EU, "DF", raiz=str(tmp_path))
    yield w
    w.fechar()


def _ids(ws, tabela, onde="1 = 1", params=()):
    with ws.leitura() as ex:
        return {r["id"] for r in ex.todos(f"SELECT id FROM {tabela} WHERE {onde}", params)}


def _direto(conn, sql, params=()):
    with conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def test_pull_inicial_traz_o_escopo_da_pessoa(ccar, cen, ws):
    r = _puxar(ccar, ws)
    assert r["primeira"] is True
    # Cargas: as minhas e as sem responsável da passagem na minha fila; nem a de outra pessoa nem a fora da fila.
    assert _ids(ws, "carga_trabalho") >= set(cen.minhas) | set(cen.livres_b)
    assert cen.dele not in _ids(ws, "carga_trabalho") and cen.livre_c not in _ids(ws, "carga_trabalho")
    assert _ids(ws, "fila_folha") == {cen.fila_b}
    # Contagens contra consultas diretas.
    (n_cargas,) = _direto(
        ccar,
        f"SELECT count(*) FROM {S}.carga_trabalho WHERE uf = 'DF' AND (responsavel = %s OR (responsavel IS NULL "
        f"AND id_lote_etapa IN (SELECT id_lote_etapa FROM {S}.fila_folha WHERE responsavel = %s "
        "AND atribuida_em IS NULL)))",
        (EU, EU),
    )[0]
    (n_lotes,), (n_le,) = (
        _direto(ccar, f"SELECT count(*) FROM {S}.{t} WHERE uf = 'DF'")[0] for t in ("lote", "lote_etapa")
    )
    assert r["tabelas"]["carga_trabalho"]["inseridas"] == n_cargas == len(_ids(ws, "carga_trabalho"))
    assert r["tabelas"]["lote"]["inseridas"] == n_lotes == len(_ids(ws, "lote"))
    assert r["tabelas"]["lote_etapa"]["inseridas"] == n_le == len(_ids(ws, "lote_etapa"))
    with ws.leitura() as ex:
        assert ex.um("SELECT count(*) AS n FROM tema WHERE id = ?", (cen.tema,))["n"] == 1
        assert ex.um("SELECT count(*) AS n FROM fluxo_etapa WHERE id = ?", (cen.etapa,))["n"] == 1
        assert ex.um("SELECT count(*) AS n FROM outbox")["n"] == 0
        c = ex.um("SELECT * FROM carga_trabalho WHERE id = ?", (cen.minhas[0],))
        assert c["sujo"] == 0 and c["xmin"] == pytest.approx(-44.9) and c["cy"] == pytest.approx(-19.975)
        (versao,) = _direto(ccar, f"SELECT atualizado_em FROM {S}.carga_trabalho WHERE id = %s", (cen.minhas[0],))[0]
        assert c["versao_base"] == iso_exato(versao)
        # A execução local enxerga: minhas cargas no workspace.
        assert {m["id"] for m in lc.minhas(ex)} == set(cen.minhas)
        assert ex.meta("ultima_sincronizacao") == r["servidor_agora"]


def test_segundo_pull_sem_mudancas_traz_zero_linhas(ccar, cen, ws):
    _puxar(ccar, ws)
    r = _puxar(ccar, ws)
    assert r["primeira"] is False and r["recebidas"] == 0 and r["linhas"] == 0


def test_mudanca_direta_no_banco_aparece(ccar, cen, ws):
    _puxar(ccar, ws)
    cen.executar(f"UPDATE {S}.carga_trabalho SET concluido = true WHERE id = %s", (cen.minhas[1],))
    r = _puxar(ccar, ws)
    assert r["tabelas"]["carga_trabalho"] == {**pull._contagem(), "recebidas": 1, "atualizadas": 1}
    with ws.leitura() as ex:
        c = ex.um("SELECT concluido, concluido_em FROM carga_trabalho WHERE id = ?", (cen.minhas[1],))
    assert c["concluido"] == 1 and c["concluido_em"] is not None
    assert _puxar(ccar, ws)["linhas"] == 0


def test_saida_e_entrada_no_escopo(ccar, cen, ws):
    _puxar(ccar, ws)
    # Reatribuída a outra pessoa e descartada pelo supervisor (o DELETE da rota): saem do workspace.
    cen.executar(f"UPDATE {S}.carga_trabalho SET responsavel = %s WHERE id = %s", (OUTRO, cen.minhas[0]))
    with ccar, ccar.cursor(cursor_factory=extras.RealDictCursor) as cur:
        assert dc.descartar(ExecutorPg(cur), "DF", [cen.minhas[2]])["tiradas"] == 1
    # Passagem C entra na minha fila: a carga sem responsável dela entra no escopo sem ter mudado.
    fila_c = cen.fila(cen.c, EU, 2)
    r = _puxar(ccar, ws)
    cargas = _ids(ws, "carga_trabalho")
    assert cen.minhas[0] not in cargas and cen.minhas[2] not in cargas and cen.minhas[1] in cargas
    assert cen.livre_c in cargas
    assert r["tabelas"]["carga_trabalho"]["removidas"] == 2 and r["tabelas"]["carga_trabalho"]["inseridas"] == 1
    assert _ids(ws, "fila_folha") == {cen.fila_b, fila_c}
    # A folha sai da fila (o supervisor tira): o item e as cargas sem responsável dela saem.
    cen.executar(f"DELETE FROM {S}.fila_folha WHERE id = %s", (cen.fila_b,))
    r = _puxar(ccar, ws)
    assert _ids(ws, "fila_folha") == {fila_c}
    assert not set(cen.livres_b) & _ids(ws, "carga_trabalho")
    # A passagem apagada sai do espelho de lote_etapa.
    cen.executar(f"DELETE FROM {S}.lote WHERE id = %s", (cen.lotes[0],))
    r = _puxar(ccar, ws)
    assert cen.a not in _ids(ws, "lote_etapa") and cen.lotes[0] not in _ids(ws, "lote")
    assert cen.minhas[1] not in _ids(ws, "carga_trabalho")
    assert r["retidas"] == 0


def test_linha_com_pendencia_nao_e_sobrescrita_nem_apagada(ccar, cen, ws):
    _puxar(ccar, ws)
    with ws.leitura() as ex:
        base = ex.um("SELECT versao_base FROM carga_trabalho WHERE id = ?", (cen.minhas[0],))["versao_base"]
    with ws.transacao() as ex:
        lc.concluir(ex, cen.minhas[0])  # pendente na outbox
        lc.concluir(ex, cen.minhas[1])
    # No servidor: a primeira mudou (o supervisor acertou a geometria) e a segunda foi tirada de mim.
    cen.executar(
        f"UPDATE {S}.carga_trabalho SET geom = ST_Multi(ST_MakeEnvelope(-44.95, -20.0, -44.9, -19.95, 4674)) "
        "WHERE id = %s",
        (cen.minhas[0],),
    )
    cen.executar(f"UPDATE {S}.carga_trabalho SET responsavel = %s WHERE id = %s", (OUTRO, cen.minhas[1]))
    r = _puxar(ccar, ws)
    t = r["tabelas"]["carga_trabalho"]
    assert t["adiadas"] == 1 and t["retidas"] == 1 and t["atualizadas"] == 0 and t["removidas"] == 0
    with ws.leitura() as ex:
        c = ex.um("SELECT * FROM carga_trabalho WHERE id = ?", (cen.minhas[0],))
        assert c["concluido"] == 1 and c["xmin"] == pytest.approx(-44.9) and c["sujo"] == 1
        assert c["versao_base"] == base  # a base continua a da edição: o C3 vê que o servidor mudou desde ela
        assert cen.minhas[1] in {x["id"] for x in ex.todos("SELECT id FROM carga_trabalho")}
        assert len(ex.pendentes()) == 2


def test_pull_inicial_de_uma_pessoa_real_bate_com_o_banco(ccar, tmp_path):
    """Dados migrados do DF: a pessoa com mais cargas."""
    ((quem, n),) = _direto(
        ccar,
        f"SELECT responsavel, count(*) FROM {S}.carga_trabalho WHERE uf = 'DF' AND responsavel IS NOT NULL "
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 1",
    )
    ((n_amostras,),) = _direto(
        ccar,
        f"SELECT count(*) FROM {S}.cq_amostra a JOIN {S}.carga_trabalho c ON c.id = a.id_carga_trabalho "
        "WHERE c.responsavel = %s",
        (quem,),
    )
    with Workspace.abrir("dev", "t_c2_medida", "DF", raiz=str(tmp_path)) as w:
        r = _puxar(ccar, w, usuario=quem)
        fila = _direto(
            ccar, f"SELECT count(*) FROM {S}.fila_folha WHERE responsavel = %s AND atribuida_em IS NULL", (quem,)
        )[0][0]
        if not fila:
            assert r["tabelas"]["carga_trabalho"]["inseridas"] == n
        assert r["tabelas"]["cq_amostra"]["inseridas"] == n_amostras
        assert _puxar(ccar, w, usuario=quem)["recebidas"] == 0


def test_consultas_do_pull_rodam_no_96(tmp_path):
    """No PostgreSQL 9.6 da GGC, com as migrações e o cenário das regras dentro de uma transação desfeita."""
    from tests.db.migracoes import aplicar
    from tests.db.test_regras import Cenario as CenarioRegras

    conn = psycopg2.connect(url("FEIXE_GGC"))
    try:
        aplicar(conn)
        with conn.cursor() as cur, conn.cursor(cursor_factory=extras.RealDictCursor) as dcur:
            regras = CenarioRegras(cur)
            le = regras.passagem("aquisicao", "em_andamento")
            minhas = {regras.carga(le, EU, x=x) for x in (-44.45, -44.35)}
            regras.carga(le, OUTRO, x=-44.25)
            le_cq = regras.passagem("cq", "pendente")
            plano = regras.plano(le_cq, "Omissão", 0)
            carga_cq = regras.carga(le_cq, EU, plano=plano, x=-44.15)
            regras.amostra(plano, carga_cq)
            with Workspace.abrir("dev", EU, "DF", raiz=str(tmp_path)) as w:
                r = pull.puxar(w, ExecutorPg(dcur))
                assert _ids(w, "carga_trabalho") == minhas | {carga_cq}
                assert _ids(w, "cq_plano") == {plano} and r["tabelas"]["cq_amostra"]["inseridas"] == 1
                assert pull.puxar(w, ExecutorPg(dcur))["recebidas"] == 0
    finally:
        conn.rollback()
        conn.close()
