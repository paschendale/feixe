"""D3a: o CQ da execução de ponta a ponta contra os bancos de dev (marcador `db`), nos dois (GGC 9.6 e CCAR 17), com as
migrações aplicadas numa transação que é desfeita no fim: pull com a visibilidade do D-66, avaliar e registrar
offline, push (INSERT, UPDATE e DELETE), ciência do APM autor, recusas e última escrita.

Pessoas (só nomes: o push e o pull recebem a conta como parâmetro; ninguém precisa logar): o avaliador, o APM que fez
a carga avaliada, outro APM e quem faz a revisão seguinte. Cenário de tests/db/test_regras.py (folha 2534, fluxo com
aquisição, CQ, correção de inspeção e envio): aquisição da revisão 1 concluída, com uma carga de cada APM; a passagem
de CQ da revisão 1 em andamento, com duas cargas de CQ do avaliador; a aquisição da revisão 2 (a revisão seguinte)
em andamento, com uma carga do revisor.
"""

from __future__ import annotations

import contextlib
import datetime as dt

import pytest
from feixe.core.dados import ExecutorPg
from feixe.core.dados.local import cq as lq
from feixe.sync import pull, push
from feixe.sync.workspace import Workspace

from tests.db.conftest import url

pytestmark = pytest.mark.db
psycopg2 = pytest.importorskip("psycopg2")
extras = pytest.importorskip("psycopg2.extras")

AVAL, APM, OUTRO, REV = "t_d3_aval", "t_d3_apm", "t_d3_outro", "t_d3_rev"
S = "mapcartacomp"
UTC = dt.timezone.utc


class Cena:
    def __init__(self, conn, tmp_path):
        from tests.db.migracoes import aplicar
        from tests.db.test_regras import Cenario

        aplicar(conn)
        self.cur = conn.cursor()
        self.dcur = conn.cursor(cursor_factory=extras.RealDictCursor)
        self.rx = ExecutorPg(self.dcur)
        self.tmp = tmp_path
        c = self.c = Cenario(self.cur)
        self.le_aq = c.passagem("aquisicao", "concluida")
        self.carga_apm = c.carga(self.le_aq, APM, concluido=True, concluido_em="2026-11-20 10:00+00", x=-44.5)
        self.carga_outro = c.carga(self.le_aq, OUTRO, concluido=True, concluido_em="2026-11-20 10:00+00", x=-44.4)
        self.le_cq = c.passagem("cq", "em_andamento")
        self.plano = c.plano(self.le_cq, "Omissão", 0)
        self.cq1 = c.carga(self.le_cq, AVAL, plano=self.plano, x=-44.5)
        self.cq2 = c.carga(self.le_cq, AVAL, plano=self.plano, x=-44.4)
        self.am1 = c.amostra(self.plano, self.cq1)
        self.am2 = c.amostra(self.plano, self.cq2)
        self.le_rev = c.passagem("aquisicao", "em_andamento", instancia=2)
        self.carga_rev = c.carga(self.le_rev, REV, x=-44.5)
        self.ws = {}

    def workspace(self, conta):
        if conta not in self.ws:
            self.ws[conta] = Workspace.abrir("dev", conta, "DF", raiz=str(self.tmp / conta))
        return self.ws[conta]

    def puxar(self, conta):
        return pull.puxar(self.workspace(conta), self.rx, usuario=conta)

    def enviar(self, conta):
        @contextlib.contextmanager
        def remota():
            yield self.rx  # a transação de fora é desfeita no fim

        return push.enviar(self.workspace(conta), remota, usuario=conta)

    def linha(self, tabela, onde, params):
        self.dcur.execute(f"SELECT * FROM {S}.{tabela} WHERE {onde}", params)
        return self.dcur.fetchone()

    def direto(self, sql, params=()):
        """Mudança direta na CCAR (supervisor, tabela online) com a hora de agora de verdade: o gatilho grava now(),
        que dentro da transação do teste é sempre a mesma hora, e a última escrita precisa de versões diferentes."""
        self.cur.execute("SET LOCAL session_replication_role = replica")
        self.cur.execute(sql, params)
        self.cur.execute("SET LOCAL session_replication_role = origin")

    def uuids(self, conta, tabela="cq_inspecao"):
        with self.workspace(conta).leitura() as ex:
            return {r["uuid"] for r in ex.todos(f"SELECT uuid FROM {tabela}")}

    def fechar(self):
        for w in self.ws.values():
            w.fechar()


@pytest.fixture(params=["FEIXE_CCAR", "FEIXE_GGC"], ids=["ccar17", "ggc96"])
def cena(request, tmp_path):
    conn = psycopg2.connect(url(request.param))
    c = None
    try:
        c = Cena(conn, tmp_path)
        yield c
    finally:
        if c is not None:
            c.fechar()
        conn.rollback()
        conn.close()


def _avaliar_e_registrar(cena):
    """O avaliador, offline: avalia a primeira amostra não conforme e registra duas ocorrências (uma na carga do APM,
    outra na do outro APM)."""
    cena.puxar(AVAL)
    hora = dt.datetime.now(UTC) - dt.timedelta(minutes=30)
    ws = cena.workspace(AVAL)
    with ws.transacao(hora) as ex:
        r = lq.avaliar(ex, cena.am1, 0, "faltou trecho")
        o1 = lq.registrar(ex, -44.47, -19.97, cena.cq1, "trecho omitido")["ocorrencia"]["uuid"]
        o2 = lq.registrar(ex, -44.37, -19.97, cena.cq2, "outro trecho")["ocorrencia"]["uuid"]
    assert r["carga"]["concluido"] is True and r["proxima"]["amostra"]["id"] == cena.am2
    return hora, o1, o2


def test_avaliar_e_registrar_offline_e_enviar(cena):
    hora, o1, o2 = _avaliar_e_registrar(cena)
    with cena.workspace(AVAL).leitura() as ex:
        assert (
            ex.um("SELECT elemento FROM atividade WHERE id = ?", (cena.c.ativ_cq["Omissão"],))["elemento"] == "Omissão"
        )
    r = cena.enviar(AVAL)
    assert r["resultados"]["aplicado"] == 3 and r["avisos"] == [], r
    am = cena.linha("cq_amostra", "id = %s", (cena.am1,))
    assert am["status"] == 0 and am["avaliado_por"] == AVAL and abs(am["avaliado_em"] - hora) < dt.timedelta(seconds=5)
    carga = cena.linha("carga_trabalho", "id = %s", (cena.cq1,))
    assert carga["concluido"] and carga["concluido_em"] == am["avaliado_em"]  # a hora da avaliação, não a do push
    oc1 = cena.linha("cq_inspecao", "uuid = %s", (o1,))
    oc2 = cena.linha("cq_inspecao", "uuid = %s", (o2,))
    assert (oc1["id_lote_etapa"], oc1["id_carga_avaliada"], oc1["elemento"]) == (cena.le_cq, cena.carga_apm, "Omissão")
    assert oc2["id_carga_avaliada"] == cena.carga_outro and oc1["responsavel"] == AVAL
    with cena.workspace(AVAL).leitura() as ex:
        local = lq.ocorrencia(ex, o1)
        c_local = ex.um("SELECT concluido, sujo FROM carga_trabalho WHERE id = ?", (cena.cq1,))
        assert ex.pendentes() == []
    assert local["id"] == oc1["id"] and local["id_carga_avaliada"] == cena.carga_apm and local["enviada"]
    assert c_local == {"concluido": 1, "sujo": 0}
    assert cena.puxar(AVAL)["tabelas"]["cq_inspecao"]["removidas"] == 0


def test_apm_autor_recebe_e_da_ciencia_e_a_revisao_seguinte_e_as_cegas(cena):
    _, o1, o2 = _avaliar_e_registrar(cena)
    cena.enviar(AVAL)
    cena.puxar(APM)
    assert cena.uuids(APM) == {o1}  # só a que aponta a carga dele
    with cena.workspace(APM).transacao() as ex:
        assert lq.ocorrencia(ex, o1)["pode_ciente"]
        lq.ciente(ex, o1)
    r = cena.enviar(APM)
    assert r["resultados"]["aplicado"] == 1, r
    oc = cena.linha("cq_inspecao", "uuid = %s", (o1,))
    assert oc["ciente_por"] == APM and oc["ciente_em"] is not None
    # A revisão seguinte é às cegas.
    cena.puxar(REV)
    assert cena.uuids(REV) == set()
    # Com "incluir correções a serem feitas", as não tratadas da folha vêm como lista de correção.
    cena.direto(
        f"UPDATE {S}.lote_etapa SET expor_ocorrencias = true, atualizado_em = clock_timestamp() WHERE id = %s",
        (cena.le_rev,),
    )
    cena.puxar(REV)
    assert cena.uuids(REV) == {o1, o2}
    with cena.workspace(REV).leitura() as ex:
        assert {o["motivo"] for o in lq.ocorrencias(ex, id_lote=cena.c.lote)} == {"correcao"}
    cena.direto(f"UPDATE {S}.cq_inspecao SET tratado = true, atualizado_em = clock_timestamp() WHERE uuid = %s", (o2,))
    cena.puxar(REV)
    assert cena.uuids(REV) == {o1}


def test_recusas_no_servidor(cena):
    _, o1, o2 = _avaliar_e_registrar(cena)
    cena.enviar(AVAL)
    # Ciência por quem não é o autor: o workspace do APM tem a ocorrência da carga do outro apontando a dele (dado
    # velho); o servidor confere o autor de verdade.
    cena.puxar(APM)
    oc2 = cena.linha("cq_inspecao", "uuid = %s", (o2,))
    with cena.workspace(APM).transacao() as ex:
        linha = {k: oc2[k] for k in ("id", "id_lote", "id_lote_etapa", "id_carga_trabalho", "uf", "elemento",
                                      "anotacao", "responsavel", "tratado", "criado_em", "criado_por", "atualizado_em",
                                      "atualizado_por")}  # fmt: skip
        linha.update(uuid=o2, id_carga_avaliada=cena.carga_apm, geom=bytes.fromhex("0101000000" + "00" * 16))
        ex.gravar_remoto("cq_inspecao", linha)
        lq.ciente(ex, o2)
    r = cena.enviar(APM)
    assert r["resultados"]["recusado"] == 1 and "só quem fez a carga" in r["avisos"][0], r
    assert cena.linha("cq_inspecao", "uuid = %s", (o2,))["ciente_em"] is None
    # Com a passagem de CQ encerrada pelo supervisor: avaliar, editar e registrar são recusados e voltam ao da CCAR.
    with cena.workspace(AVAL).transacao() as ex:
        lq.avaliar(ex, cena.am2, 1)
        lq.editar(ex, o1, "anotação tardia")
        nova = lq.registrar(ex, -44.47, -19.96, cena.cq1)["ocorrencia"]["uuid"]
    cena.c.mudar(cena.le_cq, "concluida")
    r = cena.enviar(AVAL)
    assert r["resultados"]["recusado"] == 3, r
    assert all("encerrada pelo supervisor" in a for a in r["avisos"]), r["avisos"]
    with cena.workspace(AVAL).leitura() as ex:
        assert ex.um("SELECT status FROM cq_amostra WHERE id = ?", (cena.am2,))["status"] is None
        assert ex.um("SELECT concluido FROM carga_trabalho WHERE id = ?", (cena.cq2,))["concluido"] == 0
        assert ex.um("SELECT anotacao FROM cq_inspecao WHERE uuid = ?", (o1,))["anotacao"] == "trecho omitido"
        assert ex.um("SELECT 1 AS x FROM cq_inspecao WHERE uuid = ?", (nova,)) is None
        recusas = ex.todos("SELECT tabela FROM sync_log WHERE resultado = 'recusado'")
    assert sorted(x["tabela"] for x in recusas) == ["cq_amostra", "cq_inspecao", "cq_inspecao"]
    assert cena.linha("cq_inspecao", "uuid = %s", (nova,)) is None


def test_apagar_a_propria_e_a_criada_offline(cena):
    _, o1, _ = _avaliar_e_registrar(cena)
    with cena.workspace(AVAL).transacao() as ex:
        offline = lq.registrar(ex, -44.47, -19.96, cena.cq1)["ocorrencia"]["uuid"]
        lq.apagar(ex, offline)  # criada e apagada antes de enviar: as duas vão, em ordem
    r = cena.enviar(AVAL)
    assert r["resultados"]["recusado"] == 0 and r["enviados"] == 5, r
    assert cena.linha("cq_inspecao", "uuid = %s", (offline,)) is None
    with cena.workspace(AVAL).transacao() as ex:
        lq.apagar(ex, o1)
    r = cena.enviar(AVAL)
    assert r["resultados"]["aplicado"] == 1, r
    assert cena.linha("cq_inspecao", "uuid = %s", (o1,)) is None
    assert o1 not in cena.uuids(AVAL)


def test_ultima_escrita_na_amostra(cena):
    cena.puxar(AVAL)
    agora = dt.datetime.now(UTC)
    # Conflito perdido: a ação local é de ontem e a CCAR mudou a observação agora.
    with cena.workspace(AVAL).transacao(agora - dt.timedelta(days=1)) as ex:
        lq.avaliar(ex, cena.am1, 1, "local")
    cena.direto(
        f"UPDATE {S}.cq_amostra SET observacao = 'servidor', atualizado_em = clock_timestamp(), "
        "atualizado_por = 'sup' WHERE id = %s",
        (cena.am1,),
    )
    r = cena.enviar(AVAL)
    assert r["resultados"]["conflito_perdido"] == 1, r
    assert cena.linha("cq_amostra", "id = %s", (cena.am1,))["observacao"] == "servidor"
    with cena.workspace(AVAL).leitura() as ex:
        assert ex.um("SELECT observacao FROM cq_amostra WHERE id = ?", (cena.am1,))["observacao"] == "servidor"
    # Conflito vencido: a CCAR mudou antes da ação local (mais nova).
    cena.direto(
        f"UPDATE {S}.cq_amostra SET observacao = 'antes', atualizado_em = clock_timestamp() - interval '1 hour' "
        "WHERE id = %s",
        (cena.am2,),
    )
    with cena.workspace(AVAL).transacao() as ex:
        lq.avaliar(ex, cena.am2, 0, "depois")
    r = cena.enviar(AVAL)
    assert r["resultados"]["conflito_vencido"] == 1, r
    assert cena.linha("cq_amostra", "id = %s", (cena.am2,))["observacao"] == "depois"
