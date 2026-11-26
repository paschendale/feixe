"""D5: correção de inspeção no banco, nos dois (GGC 9.6 e CCAR 17), em transações desfeitas: abrir a correção gera a
carga da folha (ou começa já, sem nada a tratar), o Distribuir de sempre a dá a alguém, a última ocorrência tratada
conclui a carga da folha (`t20_correcao`) e põe a folha em Esperando você; quem está na correção recebe pelo pull
todas as ocorrências da folha (todas as revisões), trata offline e o push leva, com recusa fora da passagem aberta.

Cenário (`test_regras.Cenario`): aquisição > CQ > correção de inspeção (atividade sem geração definida, que conta como
manual) > envio à GCQ, na folha 2534. Ocorrências registradas pelo avaliador nas passagens de CQ das revisões 1 e 2.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import uuid

import psycopg2.extras
import pytest
from feixe.core.dados import ExecutorPg
from feixe.core.dados import cargas as dc
from feixe.core.dados import filas as dfi
from feixe.core.dados import lotes as dl
from feixe.core.dados import painel as dp
from feixe.core.dados.local import cq as lq
from feixe.sync import pull, push
from feixe.sync.workspace import Workspace

from tests.db.migracoes import aplicar
from tests.db.test_atribuir import _conta
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db
UTC = dt.timezone.utc
OPERADOR, OUTRO = "t_apm_a", "t_apm_b"


@pytest.fixture
def amb(banco, tmp_path):
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        cen = Cenario(cur)
        _conta(cur, OPERADOR)
        _conta(cur, OUTRO)
        ex = ExecutorPg(dcur)
        abertos = []

        def workspace(conta):
            w = Workspace.abrir("dev", conta, "DF", raiz=str(tmp_path / conta))
            abertos.append(w)
            return w

        try:
            yield cen, ex, workspace
        finally:
            for w in abertos:
                w.fechar()


def _ocorrencias(cen, ex, n_por_revisao=(2, 1), tratadas=0):
    """Passagens de CQ das revisões 1 e 2 (concluídas) com as ocorrências do avaliador; as `tratadas` primeiras já
    tratadas numa correção anterior."""
    uuids = []
    for rev, n in enumerate(n_por_revisao, start=1):
        le = cen.passagem("cq", "concluida", revisao=rev, instancia=rev)
        for k in range(n):
            u = str(uuid.uuid4())
            ex.executar(
                "INSERT INTO mapcartacomp.cq_inspecao (uuid, id_lote, id_lote_etapa, uf, elemento, geom, anotacao, "
                "tratado) VALUES (%s, %s, %s, 'DF', 'Omissão', ST_SetSRID(ST_MakePoint(%s, -19.97), 4674), %s, %s)",
                (u, cen.lote, le, -44.47 + 0.01 * k, f"rev {rev} nº {k}", len(uuids) < tratadas),
            )
            uuids.append(u)
    return uuids


def _correcao(cen, ex):
    le = cen.passagem("correcao_inspecao", "pendente", revisao=2)
    return le, dc.preparar(ex, "DF", [le])


def _carga_da_folha(ex, le):
    return ex.todos(
        "SELECT id, uuid::text AS uuid, responsavel, concluido, concluido_em, geocodigo FROM "
        "mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s",
        (le,),
    )


def _esperando(ex, cen):
    return [f for g in dp.esperando(ex, "DF") for f in g["folhas"] if f["id_lote"] == cen.lote]


def test_abrir_distribuir_e_a_ultima_tratada_poe_a_folha_em_esperando(amb):
    cen, ex, _ = amb
    oc = _ocorrencias(cen, ex, tratadas=1)
    le, r = _correcao(cen, ex)
    (g,) = r["geradas"]
    assert g["gravadas"] == 1 and g["ocorrencias"] == 2 and not r["iniciadas"] and not r["avisos"]
    (carga,) = _carga_da_folha(ex, le)
    assert carga["responsavel"] is None and carga["geocodigo"] is None and not carga["concluido"]
    # A carga é a folha inteira.
    assert ex.um(
        "SELECT ST_Equals(c.geom, ST_Multi(a.geom)) AS igual FROM mapcartacomp.carga_trabalho c, "
        "mapcartctrl.t_articulacao_scn a JOIN mapcartacomp.lote l ON l.id_articulacao_scn = a.id_articulacao_scn "
        "WHERE c.id = %s AND l.id = %s",
        (carga["id"], cen.lote),
    )["igual"]
    # O Distribuir de sempre: a folha vai a uma pessoa, e a etapa começa.
    sug = dfi.sugestao(ex, "DF", [cen.lote])
    (f,) = sug["folhas"]
    assert f["a_atribuir"] == 1 and f["sugerida"] is not None
    d = dfi.distribuir_uma(ex, "DF", le, OPERADOR)
    assert d["atribuida"]["atribuidas"] == 1
    assert ex.um("SELECT situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))["situacao"] == "em_andamento"
    assert _esperando(ex, cen) == []
    lote = dl.um(ex, cen.lote)
    assert lote["ocorrencias"] == {"total": 3, "tratadas": 1}

    # Tratar a penúltima não conclui; a última conclui a carga da folha com a hora dela.
    hora = ex.um("SELECT now() + interval '1 minute' AS h")["h"]  # depois da tratada na correção anterior
    ex.executar("UPDATE mapcartacomp.cq_inspecao SET tratado = true, tratado_em = %s WHERE uuid = %s", (hora, oc[1]))
    assert not _carga_da_folha(ex, le)[0]["concluido"]
    ultima = hora + dt.timedelta(minutes=7)
    ex.executar("UPDATE mapcartacomp.cq_inspecao SET tratado = true, tratado_em = %s WHERE uuid = %s", (ultima, oc[2]))
    (carga,) = _carga_da_folha(ex, le)
    assert carga["concluido"] and carga["concluido_em"] == ultima
    (f,) = _esperando(ex, cen)
    assert f["ocorrencias_tratadas"] == 3 and f["situacao"] == "em_andamento"
    # Desmarcar com a etapa aberta reabre a carga e tira a folha de Esperando.
    ex.executar("UPDATE mapcartacomp.cq_inspecao SET tratado = false WHERE uuid = %s", (oc[2],))
    assert not _carga_da_folha(ex, le)[0]["concluido"] and _esperando(ex, cen) == []
    # A carga da folha numa passagem encerrada não muda mais.
    ex.executar("UPDATE mapcartacomp.lote_etapa SET situacao = 'concluida', concluida_em = now() WHERE id = %s", (le,))
    ex.executar("UPDATE mapcartacomp.cq_inspecao SET tratado = true WHERE uuid = %s", (oc[2],))
    assert not _carga_da_folha(ex, le)[0]["concluido"]


def test_nada_a_tratar_comeca_ja_e_sem_atividade_avisa(amb):
    cen, ex, _ = amb
    _ocorrencias(cen, ex, n_por_revisao=(1,), tratadas=1)
    le, r = _correcao(cen, ex)
    assert not r["geradas"] and [i["id_lote_etapa"] for i in r["iniciadas"]] == [le] and not r["avisos"]
    assert _carga_da_folha(ex, le) == []
    (f,) = _esperando(ex, cen)
    assert f["situacao"] == "em_andamento" and f["ocorrencias_tratadas"] == 1
    hist = ex.um("SELECT observacao FROM mapcartacomp.lote_etapa_hist WHERE id_lote_etapa = %s", (le,))
    assert "nenhuma ocorrência" in hist["observacao"]

    # Outra folha, com ocorrência a tratar e a etapa sem atividade: começa, sem cargas, e o aviso diz o que fazer.
    ex.executar("DELETE FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))
    ex.executar("UPDATE mapcartacomp.cq_inspecao SET tratado = false WHERE id_lote = %s", (cen.lote,))
    ex.executar(
        "DELETE FROM mapcartacomp.fluxo_etapa_atividade WHERE id_fluxo_etapa = %s", (cen.etapa["correcao_inspecao"],)
    )
    le, r = _correcao(cen, ex)
    (aviso,) = r["avisos"]
    assert "não tem atividade" in aviso["aviso"] and [i["id_lote_etapa"] for i in r["iniciadas"]] == [le]
    assert _esperando(ex, cen) == []  # a ocorrência continua por tratar


def test_pull_traz_todas_da_folha_e_o_push_leva_e_recusa_fora_da_passagem(amb):
    cen, ex, workspace = amb
    oc = _ocorrencias(cen, ex, tratadas=1)
    le, _ = _correcao(cen, ex)
    dfi.distribuir_uma(ex, "DF", le, OPERADOR)

    @contextlib.contextmanager
    def remota():
        yield ex  # a transação de fora é desfeita no fim

    w, w_outro = workspace(OPERADOR), workspace(OUTRO)
    pull.puxar(w, ex, usuario=OPERADOR)
    pull.puxar(w_outro, ex, usuario=OUTRO)
    with w.leitura() as lx:
        assert {o["uuid"] for o in lq.ocorrencias(lx, id_lote=cen.lote)} == set(oc)  # todas, de todas as revisões
    with w_outro.leitura() as lx:
        assert lx.um("SELECT count(*) AS n FROM cq_inspecao")["n"] == 0  # quem não está na correção, nada

    # Offline: trata as duas que faltam; a carga da folha conclui no workspace.
    hora = dt.datetime.now(UTC) - dt.timedelta(minutes=20)
    with w.transacao(hora) as lx:
        lq.tratar(lx, oc[1])
        r = lq.tratar(lx, oc[2])
    assert r["progresso"]["pendentes"] == 0
    res = push.enviar(w, remota, usuario=OPERADOR)
    assert res["resultados"]["aplicado"] == 2, res
    srv = ex.um("SELECT tratado, tratado_por, tratado_em FROM mapcartacomp.cq_inspecao WHERE uuid = %s", (oc[2],))
    assert srv["tratado"] and srv["tratado_por"] == OPERADOR
    assert abs((srv["tratado_em"] - hora).total_seconds()) < 5  # a hora da ação (corrigida pelo relógio)
    (carga,) = _carga_da_folha(ex, le)
    assert carga["concluido"]
    with w.leitura() as lx:
        local = lx.um("SELECT concluido, sujo FROM carga_trabalho WHERE uuid = ?", (carga["uuid"],))
        assert local["concluido"] == 1 and local["sujo"] == 0 and lx.pendentes() == []
    assert [f["id_lote"] for f in _esperando(ex, cen)] == [cen.lote]

    # Desmarca offline, mas o supervisor encerrou a correção antes do push: recusa, e o workspace volta à CCAR.
    with w.transacao() as lx:
        lq.tratar(lx, oc[2], False)
    ex.executar("UPDATE mapcartacomp.lote_etapa SET situacao = 'concluida', concluida_em = now() WHERE id = %s", (le,))
    res = push.enviar(w, remota, usuario=OPERADOR)
    assert res["resultados"]["recusado"] == 1 and "correção de inspeção aberta" in res["avisos"][0], res
    assert ex.um("SELECT tratado FROM mapcartacomp.cq_inspecao WHERE uuid = %s", (oc[2],))["tratado"]
    with w.leitura() as lx:
        assert lx.um("SELECT tratado FROM cq_inspecao WHERE uuid = ?", (oc[2],))["tratado"] == 1
        assert lx.um("SELECT concluido FROM carga_trabalho WHERE uuid = ?", (carga["uuid"],))["concluido"] == 1
        log = lx.um("SELECT resultado FROM sync_log WHERE uuid = ? ORDER BY id DESC LIMIT 1", (oc[2],))
    assert log["resultado"] == "recusado"


def test_push_recusa_quem_nao_esta_com_a_folha(amb):
    cen, ex, workspace = amb
    oc = _ocorrencias(cen, ex)
    le, _ = _correcao(cen, ex)
    dfi.distribuir_uma(ex, "DF", le, OPERADOR)

    @contextlib.contextmanager
    def remota():
        yield ex

    w = workspace(OPERADOR)
    pull.puxar(w, ex, usuario=OPERADOR)
    with w.transacao() as lx:
        lq.tratar(lx, oc[0])
    # O supervisor passou a folha a outra pessoa antes do push.
    dfi.distribuir_uma(ex, "DF", le, OUTRO)
    res = push.enviar(w, remota, usuario=OPERADOR)
    assert res["resultados"]["recusado"] == 1, res
    assert not ex.um("SELECT tratado FROM mapcartacomp.cq_inspecao WHERE uuid = %s", (oc[0],))["tratado"]
