"""C3: push do workspace para a CCAR de dev (marcador `db`), com duas cópias de workspace da mesma conta.

Como no C2, o cenário é gravado de verdade na CCAR de dev (cada mudança na sua transação) e apagado no fim, com o
`sync_log` da conta de teste. A conta (`t_c3_apm`) é cadastrada no SGBC de dev com lotação DF e perfil O no projeto 5,
porque o puxar da fila confere o perfil de novo no servidor; sai no fim. A conexão é a do `postgres`: o push recebe a
conta do workspace como `usuario` (em produção é o `current_user`, e `Sincronizacao` confere).

Cada teste confere que nada se perde sem registro: todo item que saiu da outbox está no `sync_log` dos dois lados.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid

import pytest
from feixe.core.dados import ExecutorPg
from feixe.core.dados.local import cargas as lc
from feixe.sync import pull, push
from feixe.sync.workspace import Workspace, iso_exato

from tests.db.conftest import url

pytestmark = pytest.mark.db
psycopg2 = pytest.importorskip("psycopg2")
extras = pytest.importorskip("psycopg2.extras")

EU = "t_c3_apm"
OUTRO = "t_c3_outro"
S = "mapcartacomp"
UTC = dt.timezone.utc


def _uid() -> str:
    return str(uuid.uuid4())


def _antes(minutos: float) -> dt.datetime:
    return dt.datetime.now(UTC) - dt.timedelta(minutes=minutos)


class Cenario:
    """Tema, atividade e fluxo próprios e dois lotes livres no DF: passagem A em andamento com três cargas minhas e
    uma de outra pessoa; passagem B pendente, na minha fila, com duas cargas sem responsável."""

    def __init__(self, conn):
        self.conn = conn
        tag = uuid.uuid4().hex[:8]
        self.cod_usuario = self._conta(EU)
        self.tema = self.um(f"INSERT INTO {S}.tema (nome) VALUES (%s) RETURNING id", (f"teste_push_{tag}",))
        self.ativ = self.um(
            f"INSERT INTO {S}.atividade (cod_projeto, id_tema, fase, nome) VALUES (5, %s, 'aquisicao', %s) "
            "RETURNING id",
            (self.tema, f"teste push {tag}"),
        )
        self.fluxo = self.um(
            f"INSERT INTO {S}.fluxo (cod_projeto, id_tema, uf, nome) VALUES (5, %s, 'DF', %s) RETURNING id",
            (self.tema, f"DF teste push {tag}"),
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
        self.minhas = [self.carga(self.a, EU, x) for x in (-44.9, -44.8, -44.7)]
        self.dele = self.carga(self.a, OUTRO, -44.6)
        self.livres_b = [self.carga(self.b, None, x) for x in (-44.9, -44.8)]
        self.fila_b = self.um(
            f"INSERT INTO {S}.fila_folha (uuid, id_lote_etapa, responsavel, ordem) VALUES (%s, %s, %s, 1) RETURNING id",
            (_uid(), self.b, EU),
        )

    def executar(self, sql, params=()):
        with self.conn, self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()[0] if cur.description else None

    um = executar

    def linha(self, tabela, id_):
        with self.conn, self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {S}.{tabela} WHERE id = %s", (id_,))
            return cur.fetchone()

    def _conta(self, conta):
        with self.conn, self.conn.cursor() as cur:
            cur.execute("SET LOCAL session_replication_role = replica")
            cur.execute(
                "INSERT INTO mapcartctrl.t_usuario (nom_contausuario, nom_usuario, dsc_lotacao, ind_contaativa) "
                "VALUES (%s, %s, 'DF', true) RETURNING cod_usuario",
                (conta, f"Teste {conta}"),
            )
            cod = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO mapcartctrl.t_prd_perfil_usuarioprojeto (cd_usuario, cd_projeto, cd_perfil) "
                "VALUES (%s, 5, 'O')",
                (cod,),
            )
            return cod

    def passagem(self, nome, situacao):
        lote = self.um(
            f"INSERT INTO {S}.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome, geom) VALUES "
            "(%s, 5, %s, %s, 'DF', 'livre', %s, ST_Multi(ST_MakeEnvelope(-45, -20.5, -44, -19.5, 4674))) RETURNING id",
            (_uid(), self.tema, self.fluxo, f"P{nome}"),
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

    def logs(self, uuid_):
        with self.conn, self.conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            cur.execute(f"SELECT resultado, detalhe FROM {S}.sync_log WHERE uuid = %s ORDER BY id", (uuid_,))
            return cur.fetchall()

    def limpar(self):
        for lote in self.lotes:
            self.executar(f"DELETE FROM {S}.lote WHERE id = %s", (lote,))
        self.executar(f"DELETE FROM {S}.fluxo WHERE id = %s", (self.fluxo,))
        self.executar(f"DELETE FROM {S}.atividade WHERE id = %s", (self.ativ,))
        self.executar(f"DELETE FROM {S}.tema WHERE id = %s", (self.tema,))
        self.executar(f"DELETE FROM {S}.sync_log WHERE usuario = %s", (EU,))
        with self.conn, self.conn.cursor() as cur:
            cur.execute("SET LOCAL session_replication_role = replica")
            cur.execute(
                "DELETE FROM mapcartctrl.t_prd_perfil_usuarioprojeto WHERE cd_usuario = %s", (self.cod_usuario,)
            )
            cur.execute("DELETE FROM mapcartctrl.t_usuario WHERE cod_usuario = %s", (self.cod_usuario,))


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


def _ws(tmp_path, nome):
    return Workspace.abrir("dev", EU, "DF", raiz=str(tmp_path / nome))


@pytest.fixture
def ws1(tmp_path):
    w = _ws(tmp_path, "estacao1")
    yield w
    w.fechar()


@pytest.fixture
def ws2(tmp_path):
    w = _ws(tmp_path, "estacao2")
    yield w
    w.fechar()


def _puxar(conn, ws):
    with conn, conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return pull.puxar(ws, ExecutorPg(cur))


def _remota(conn):
    @contextlib.contextmanager
    def abrir():
        with conn, conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
            yield ExecutorPg(cur)

    return abrir


def _enviar(conn, ws):
    return push.enviar(ws, _remota(conn))


def _chaves(ws):
    with ws.leitura() as ex:
        return {i["chave"]: (i["tabela"], i["uuid"]) for i in ex.pendentes()}


def _registrado(cen, ws, chaves):
    """Nada se perde sem registro: cada item que saiu da outbox está no sync_log da CCAR e no local."""
    with ws.leitura() as ex:
        assert ex.um("SELECT count(*) AS n FROM outbox")["n"] == 0
        locais = [r["detalhe"] for r in ex.todos("SELECT detalhe FROM sync_log")]
    import json

    no_local = {c for d in locais if d for c in (json.loads(d).get("itens") or [])}
    for chave, (_, u) in chaves.items():
        assert any(chave in (log["detalhe"].get("itens") or []) for log in cen.logs(u)), chave
        assert chave in no_local, chave


def _local(ws, tabela, id_):
    with ws.leitura() as ex:
        return ex.um(f"SELECT * FROM {tabela} WHERE id = ?", (id_,))


def test_aplicado(ccar, cen, ws1):
    _puxar(ccar, ws1)
    hora = _antes(3)
    with ws1.transacao(hora) as ex:
        lc.concluir(ex, cen.minhas[0])
    chaves = _chaves(ws1)
    r = _enviar(ccar, ws1)
    assert r["resultados"]["aplicado"] == 1 and r["avisos"] == [] and abs(r["desvio_s"]) < 120
    srv = cen.linha("carga_trabalho", cen.minhas[0])
    assert srv["concluido"] is True and abs((srv["concluido_em"] - hora).total_seconds()) < 120
    c = _local(ws1, "carga_trabalho", cen.minhas[0])
    assert c["sujo"] == 0 and c["versao_base"] == iso_exato(srv["atualizado_em"])
    (log,) = cen.logs(c["uuid"])
    assert log["resultado"] == "aplicado" and log["detalhe"]["versao"] == c["versao_base"]
    _registrado(cen, ws1, chaves)
    # O pull seguinte não traz nada: o workspace já tem a versão que o push gravou.
    assert _puxar(ccar, ws1)["tabelas"]["carga_trabalho"]["recebidas"] == 0


def test_conflito_vencido_pela_hora_da_acao(ccar, cen, ws1, ws2):
    """As duas estações concluem a mesma carga; a 2 envia primeiro. A ação da 1 é mais nova que a da 2 (embora mais
    velha que o envio da 2): vence, e o valor do servidor vai para o detalhe com a hora da ação que o gravou."""
    _puxar(ccar, ws1)
    _puxar(ccar, ws2)
    h2, h1 = _antes(10), _antes(5)
    with ws2.transacao(h2) as ex:
        lc.concluir(ex, cen.minhas[0])
    _enviar(ccar, ws2)
    with ws1.transacao(h1) as ex:
        lc.concluir(ex, cen.minhas[0])
    chaves = _chaves(ws1)
    r = _enviar(ccar, ws1)
    assert r["resultados"]["conflito_vencido"] == 1
    srv = cen.linha("carga_trabalho", cen.minhas[0])
    assert abs((srv["concluido_em"] - h1).total_seconds()) < 120
    log = cen.logs(srv["uuid"])[-1]
    d = log["detalhe"]
    assert log["resultado"] == "conflito_vencido" and d["descartado"] == "servidor"
    assert d["servidor"]["origem_em"] == "acao" and d["servidor"]["por"] == EU
    assert abs((dt.datetime.fromisoformat(d["servidor"]["em"].replace("Z", "+00:00")) - h2).total_seconds()) < 120
    assert d["servidor"]["valores"]["concluido"] is True and d["local"]["valores"]["concluido"] is True
    assert _local(ws1, "carga_trabalho", cen.minhas[0])["versao_base"] == iso_exato(srv["atualizado_em"])
    _registrado(cen, ws1, chaves)


def test_conflito_perdido(ccar, cen, ws1, ws2):
    """A estação 1 concluiu antes, offline; a 2 concluiu depois e enviou primeiro. A 1 perde: o workspace dela fica
    com a conclusão da 2 e a dela vai para o detalhe."""
    _puxar(ccar, ws1)
    _puxar(ccar, ws2)
    h1, h2 = _antes(10), _antes(5)
    with ws1.transacao(h1) as ex:
        lc.concluir(ex, cen.minhas[1])
    with ws2.transacao(h2) as ex:
        lc.concluir(ex, cen.minhas[1])
    _enviar(ccar, ws2)
    depois_da_2 = cen.linha("carga_trabalho", cen.minhas[1])
    chaves = _chaves(ws1)
    r = _enviar(ccar, ws1)
    assert r["resultados"]["conflito_perdido"] == 1 and len(r["avisos"]) == 1
    srv = cen.linha("carga_trabalho", cen.minhas[1])
    assert srv["concluido_em"] == depois_da_2["concluido_em"] and srv["atualizado_em"] == depois_da_2["atualizado_em"]
    c = _local(ws1, "carga_trabalho", cen.minhas[1])
    assert c["sujo"] == 0 and c["concluido_em"].startswith(iso_exato(srv["concluido_em"])[:19])
    log = cen.logs(srv["uuid"])[-1]
    assert log["resultado"] == "conflito_perdido" and log["detalhe"]["descartado"] == "local"
    assert log["detalhe"]["local"]["valores"]["concluido_em"].startswith(h1.strftime("%Y-%m-%dT%H:%M"))
    _registrado(cen, ws1, chaves)


def test_idempotente_quando_a_resposta_se_perde(ccar, cen, ws1, monkeypatch):
    _puxar(ccar, ws1)
    with ws1.transacao() as ex:
        lc.concluir(ex, cen.minhas[2])
    chaves = _chaves(ws1)
    real = push._finalizar

    def caiu(*a, **k):
        raise ConnectionResetError("a rede caiu depois do commit")

    monkeypatch.setattr(push, "_finalizar", caiu)
    with pytest.raises(ConnectionResetError):
        _enviar(ccar, ws1)
    assert len(_chaves(ws1)) == 1  # a CCAR aplicou, o workspace não ficou sabendo
    uuid_ = next(iter(chaves.values()))[1]
    assert len(cen.logs(uuid_)) == 1
    monkeypatch.setattr(push, "_finalizar", real)
    r = _enviar(ccar, ws1)
    assert r["repetidos"] == 1 and r["enviados"] == 0
    assert len(cen.logs(uuid_)) == 1  # não aplicou de novo nem virou conflito consigo mesmo
    srv = cen.linha("carga_trabalho", cen.minhas[2])
    c = _local(ws1, "carga_trabalho", cen.minhas[2])
    assert c["sujo"] == 0 and c["versao_base"] == iso_exato(srv["atualizado_em"])
    _registrado(cen, ws1, chaves)


def test_recusa_concluir_em_etapa_encerrada(ccar, cen, ws1):
    _puxar(ccar, ws1)
    with ws1.transacao() as ex:
        lc.concluir(ex, cen.minhas[0])
    chaves = _chaves(ws1)
    cen.executar(f"UPDATE {S}.lote_etapa SET situacao = 'concluida', concluida_em = now() WHERE id = %s", (cen.a,))
    r = _enviar(ccar, ws1)
    assert r["resultados"]["recusado"] == 1 and "encerrada" in r["avisos"][0]
    assert cen.linha("carga_trabalho", cen.minhas[0])["concluido"] is False
    c = _local(ws1, "carga_trabalho", cen.minhas[0])
    assert c["concluido"] == 0 and c["sujo"] == 0  # desfeito no workspace
    log = cen.logs(c["uuid"])[-1]
    assert log["resultado"] == "recusado" and "encerrada" in log["detalhe"]["motivo"]
    _registrado(cen, ws1, chaves)


def _concluir_todas(ws, cen):
    """Concluir a última carga pendente puxa a folha B da fila no workspace."""
    fila = None
    for i in cen.minhas:
        with ws.transacao() as ex:
            fila = lc.concluir(ex, i)["fila"]
    assert fila is not None and fila["atribuidas"] == 2
    return fila


def test_puxar_da_fila_aplicado_e_linha_criada_recebe_id(ccar, cen, ws1):
    _puxar(ccar, ws1)
    _concluir_todas(ws1, cen)
    with ws1.leitura() as ex:
        hist = ex.um("SELECT uuid, id FROM lote_etapa_hist")
    assert hist["id"] is None
    chaves = _chaves(ws1)
    r = _enviar(ccar, ws1)
    assert r["resultados"]["aplicado"] == r["enviados"] and r["resultados"]["recusado"] == 0
    assert all(cen.linha("carga_trabalho", i)["responsavel"] == EU for i in cen.livres_b)
    assert cen.linha("lote_etapa", cen.b)["situacao"] == "em_andamento"
    fila = cen.linha("fila_folha", cen.fila_b)
    assert fila["atribuida_em"] is not None and fila["atribuidas"] == 2
    id_hist = cen.um(f"SELECT id FROM {S}.lote_etapa_hist WHERE uuid = %s", (hist["uuid"],))
    with ws1.leitura() as ex:
        assert ex.um("SELECT id FROM lote_etapa_hist WHERE uuid = ?", (hist["uuid"],))["id"] == id_hist
    _registrado(cen, ws1, chaves)


def test_recusa_puxar_da_fila_quando_outra_pessoa_pegou_as_cargas(ccar, cen, ws1):
    _puxar(ccar, ws1)
    _concluir_todas(ws1, cen)
    chaves = _chaves(ws1)
    for i in cen.livres_b:
        cen.executar(f"UPDATE {S}.carga_trabalho SET responsavel = %s WHERE id = %s", (OUTRO, i))
    r = _enviar(ccar, ws1)
    assert r["resultados"]["aplicado"] == 3  # as três conclusões
    assert r["resultados"]["recusado"] == 5  # duas cargas, a passagem, o histórico e o item da fila
    assert any("outra pessoa já pegou" in a for a in r["avisos"])
    assert cen.linha("lote_etapa", cen.b)["situacao"] == "pendente"
    assert cen.linha("fila_folha", cen.fila_b)["atribuida_em"] is None
    with ws1.leitura() as ex:
        assert {c["responsavel"] for c in ex.todos(
            "SELECT responsavel FROM carga_trabalho WHERE id_lote_etapa = ?", (cen.b,))} == {OUTRO}  # fmt: skip
        assert ex.um("SELECT situacao FROM lote_etapa WHERE id = ?", (cen.b,))["situacao"] == "pendente"
        assert ex.um("SELECT count(*) AS n FROM lote_etapa_hist")["n"] == 0
        assert ex.um("SELECT atribuida_em FROM fila_folha WHERE id = ?", (cen.fila_b,))["atribuida_em"] is None
        assert lc.minhas(ex, id_lote_etapa=cen.b) == []
    fila_log = cen.logs(cen.linha("fila_folha", cen.fila_b)["uuid"])[-1]
    assert fila_log["resultado"] == "recusado" and "outra pessoa" in fila_log["detalhe"]["motivo"]
    _registrado(cen, ws1, chaves)
    # O pull seguinte tira do workspace as cargas que agora são da outra pessoa.
    _puxar(ccar, ws1)
    with ws1.leitura() as ex:
        assert not ex.todos("SELECT id FROM carga_trabalho WHERE id_lote_etapa = ?", (cen.b,))


def test_concluir_e_desfazer_juntos_e_linha_apagada(ccar, cen, ws1):
    """Concluir e desfazer seguidos viram um envio só (sem efeito na CCAR) com os dois itens no registro; a carga
    descartada na CCAR enquanto estava suja sai do workspace."""
    _puxar(ccar, ws1)
    antes = cen.linha("carga_trabalho", cen.minhas[0])
    with ws1.transacao() as ex:
        lc.concluir(ex, cen.minhas[0])
    with ws1.transacao() as ex:
        lc.desfazer(ex, cen.minhas[0])
    with ws1.transacao() as ex:
        lc.concluir(ex, cen.minhas[1])
    cen.executar(f"DELETE FROM {S}.carga_trabalho WHERE id = %s", (cen.minhas[1],))
    chaves = _chaves(ws1)
    r = _enviar(ccar, ws1)
    assert r["itens"] == 3 and r["enviados"] == 2
    assert cen.linha("carga_trabalho", cen.minhas[0])["atualizado_em"] == antes["atualizado_em"]
    (log,) = cen.logs(antes["uuid"])
    assert log["resultado"] == "aplicado" and len(log["detalhe"]["itens"]) == 2 and len(log["detalhe"]["juntados"]) == 2
    assert _local(ws1, "carga_trabalho", cen.minhas[1]) is None
    _registrado(cen, ws1, chaves)


def test_consultas_do_push_rodam_no_96(tmp_path):
    """No PostgreSQL 9.6 da GGC, com as migrações e o cenário das regras dentro de uma transação desfeita: concluir,
    juntar concluir e desfazer, e o registro no sync_log."""
    from tests.db.migracoes import aplicar
    from tests.db.test_regras import Cenario as CenarioRegras

    conn = psycopg2.connect(url("FEIXE_GGC"))
    try:
        aplicar(conn)
        with conn.cursor() as cur, conn.cursor(cursor_factory=extras.RealDictCursor) as dcur:
            regras = CenarioRegras(cur)
            le = regras.passagem("aquisicao", "em_andamento")
            a, b = (regras.carga(le, EU, x=x) for x in (-44.45, -44.35))

            @contextlib.contextmanager
            def remota():
                yield ExecutorPg(dcur)  # a transação de fora é desfeita no fim

            with Workspace.abrir("dev", EU, "DF", raiz=str(tmp_path)) as w:
                pull.puxar(w, ExecutorPg(dcur))
                with w.transacao() as ex:
                    lc.concluir(ex, a)
                with w.transacao() as ex:
                    lc.concluir(ex, b)
                with w.transacao() as ex:
                    lc.desfazer(ex, b)
                r = push.enviar(w, remota)
                assert r["enviados"] == 2 and r["resultados"]["aplicado"] == 2
                dcur.execute(f"SELECT concluido FROM {S}.carga_trabalho WHERE id = %s", (a,))
                assert dcur.fetchone()["concluido"] is True
                dcur.execute(f"SELECT count(*) AS n FROM {S}.sync_log WHERE usuario = %s", (EU,))
                assert dcur.fetchone()["n"] == 2
                assert push.enviar(w, remota)["itens"] == 0
    finally:
        conn.rollback()
        conn.close()


def test_sincronizar_de_ponta_a_ponta_como_a_conta(ccar, cen, tmp_path):
    """Como no plugin: a conta loga com a própria role (membro do grupo de dev que tem os GRANTs gerados), a
    sincronização confere o `current_user`, a primeira rodada faz o pull inicial e uma conclusão local vai para a CCAR
    pela thread de segundo plano, sem a pessoa pedir."""
    import time

    from feixe.sync.sincronizar import Sincronizacao
    from feixe.sync.trabalhador import Trabalhador

    senha = uuid.uuid4().hex
    cen.executar(
        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{EU}') THEN "
        f"CREATE ROLE {EU} LOGIN; END IF; END $$"
    )
    cen.executar(f"ALTER ROLE {EU} LOGIN PASSWORD %s", (senha,))
    cen.executar(f"GRANT feixe_dev_usuarios TO {EU}")
    dsn = psycopg2.extensions.parse_dsn(url("FEIXE_CCAR"))
    conn = psycopg2.connect(**{**dsn, "user": EU, "password": senha})
    ws = _ws(tmp_path, "conta")
    trab = None
    try:

        @contextlib.contextmanager
        def remota():
            with conn, conn.cursor(cursor_factory=extras.RealDictCursor) as cur:
                yield ExecutorPg(cur)

        terminou = []
        sinc = Sincronizacao(lambda: ws, remota, alcancavel=lambda: True, ao_terminar=terminou.append)
        r = sinc.sincronizar()
        assert r["estado"] == "ok" and r["push"] is None and r["pull"]["primeira"] is True
        with ws.transacao() as ex:
            lc.concluir(ex, cen.minhas[0])
        trab = Trabalhador(sinc.sincronizar, atraso=0.05).iniciar()
        trab.acordar()
        fim = time.monotonic() + 30
        while trab.rodadas == 0 and time.monotonic() < fim:
            time.sleep(0.05)
        assert trab.ultimo["estado"] == "ok", trab.ultimo
        assert trab.ultimo["push"]["resultados"]["aplicado"] == 1
        assert cen.linha("carga_trabalho", cen.minhas[0])["concluido"] is True
        assert sinc.estado()["pendentes"] == 0 and terminou[-1]["mudou"] is True
        (log,) = cen.logs(cen.linha("carga_trabalho", cen.minhas[0])["uuid"])
        assert log["resultado"] == "aplicado"
    finally:
        if trab is not None:
            trab.parar()
        ws.fechar()
        conn.close()
        cen.executar(f"DROP ROLE IF EXISTS {EU}")
