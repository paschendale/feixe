"""B6: fluxos e o andar da folha, pela camada de dados. Cenários DF e GO do backlog, com o status nacional derivado
em cada passo e nada mudando de etapa sem ação explícita. Transações desfeitas, nos dois bancos."""

from __future__ import annotations

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import fluxos as df
from feixe.core.dados import lotes as dl

from tests.db.migracoes import aplicar
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db

OBS = "teste"


@pytest.fixture
def amb(banco):
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        yield Cenario(cur), ExecutorPg(dcur)


def _recusa(ex, fn, *args, **kw):
    ex.cur.execute("SAVEPOINT s")
    with pytest.raises(ErroDados) as e:
        fn(ex, *args, **kw)
    ex.cur.execute("ROLLBACK TO SAVEPOINT s")
    return e.value


def _etapa(fase, conta=False, repetivel=True, obrigatoria=True, **kw):
    return {"fase": fase, "nome": f"E {fase}", "conta_revisao": conta, "repetivel": repetivel,
            "obrigatoria": obrigatoria, **kw}  # fmt: skip


def _folha(ex, uf, fluxo, mi="2535"):
    art = ex.um("SELECT id_articulacao_scn AS id FROM mapcartctrl.v_articulacao_scn_100000 WHERE cd_mi = %s", (mi,))
    lote = dl.criar_folhas(ex, uf, fluxo["id"], [art["id"]])["criados"][0]["id_lote"]
    return lote, {e["fase"] + (str(i) if e["fase"] == "x" else ""): e["id"] for i, e in enumerate(fluxo["etapas"])}


def _aberta(ex, lote):
    return ex.um(
        "SELECT id FROM mapcartacomp.lote_etapa WHERE id_lote = %s AND situacao IN ('pendente', 'em_andamento')",
        (lote,),
    )["id"]


def _passar(ex, uf, lote, etapa=None, resultado=None):
    """Abre (se pedido) a passagem da etapa, inicia e conclui; devolve o estado depois de iniciar e o final."""
    if etapa is not None:
        df.nova_passagem(ex, uf, lote, etapa, OBS)
    le = _aberta(ex, lote)
    durante = df.acao(ex, uf, le, "iniciar", OBS)
    fim = df.acao(ex, uf, le, "gcq" if resultado else "concluir", OBS, resultado)
    return durante, fim


def test_cenario_df_completo(amb):
    cen, ex = amb
    fluxo = df.criar(ex, "DF", 5, cen.tema, "DF completo", [
        _etapa("aquisicao", conta=True, repetivel=False, atividades=[cen.ativ["aquisicao"]]),
        _etapa("cq", obrigatoria=False),
        _etapa("revisao", conta=True, obrigatoria=False),
        _etapa("correcao_inspecao", obrigatoria=False),
        _etapa("correcao_topologica"),
        _etapa("envio_gcq"),
    ])  # fmt: skip
    lote, e = _folha(ex, "DF", fluxo)
    assert df.estado(ex, lote)["status_nacional"] == "PLANEJADA"
    durante, fim = _passar(ex, "DF", lote)
    assert (durante["status_nacional"], durante["revisao_atual"]) == ("EM_PRODUCAO", 1)
    assert fim["status_nacional"] == "EM_PRODUCAO" and fim["sugestao"]["id"] == e["cq"]  # sugere, não avança
    assert ex.um("SELECT count(*) AS n FROM mapcartacomp.lote_etapa WHERE id_lote = %s", (lote,))["n"] == 1
    passos = [
        ("cq", "EM_CQ", 1), ("revisao", "EM_PRODUCAO", 2), ("cq", "EM_CQ", 2),
        ("correcao_inspecao", "EM_PRODUCAO", 2), ("correcao_topologica", "EM_PRODUCAO", 2),
    ]  # fmt: skip
    for fase, status, revisao in passos:
        durante, _ = _passar(ex, "DF", lote, e[fase])
        assert (durante["status_nacional"], durante["revisao_atual"]) == (status, revisao), fase
    durante, fim = _passar(ex, "DF", lote, e["envio_gcq"], resultado="aprovada")
    assert (durante["status_nacional"], fim["status_nacional"]) == ("ENTREGUE_GCQ", "CONCLUIDA")
    hist = df.historico(ex, lote)
    assert len(hist) == 7 * 2 + 6 and {h["observacao"] for h in hist} == {OBS}  # 7 inícios e fins, 6 aberturas
    assert hist[0]["acao"] == "gcq_aprovada"


def test_cenario_go_e_devolucao(amb):
    cen, ex = amb
    fluxo = df.criar(ex, "GO", 5, cen.tema, "GO curto", [
        _etapa("aquisicao", conta=True, repetivel=False), _etapa("correcao_topologica"), _etapa("envio_gcq"),
    ])  # fmt: skip
    lote, e = _folha(ex, "GO", fluxo)
    _passar(ex, "GO", lote)
    _passar(ex, "GO", lote, e["correcao_topologica"])
    _, fim = _passar(ex, "GO", lote, e["envio_gcq"], resultado="devolvida")
    assert fim["status_nacional"] == "DEVOLVIDA"
    # Devolvida: o supervisor volta à correção topológica (nova passagem) e a folha sai de DEVOLVIDA.
    durante, _ = _passar(ex, "GO", lote, e["correcao_topologica"])
    assert durante["status_nacional"] == "EM_PRODUCAO"


def test_regras_do_andar(amb):
    cen, ex = amb
    fluxo = df.criar(ex, "DF", 5, cen.tema, "DF regras", [
        _etapa("aquisicao", conta=True, repetivel=False), _etapa("cq", obrigatoria=False), _etapa("envio_gcq"),
    ])  # fmt: skip
    lote, e = _folha(ex, "DF", fluxo)
    le = _aberta(ex, lote)
    assert "obrigatória" in _recusa(ex, df.acao, "DF", le, "pular", OBS).mensagem
    assert "só se conclui" in _recusa(ex, df.acao, "DF", le, "concluir", OBS).mensagem
    assert _recusa(ex, df.acao, "GO", le, "iniciar", OBS).status == 404
    assert "aberta" in _recusa(ex, df.nova_passagem, "DF", lote, e["cq"], OBS).mensagem
    _passar(ex, "DF", lote)
    assert "não se repete" in _recusa(ex, df.nova_passagem, "DF", lote, e["aquisicao"], OBS).mensagem
    df.nova_passagem(ex, "DF", lote, e["cq"], OBS, expor_ocorrencias=True)
    cq = _aberta(ex, lote)
    assert ex.um("SELECT expor_ocorrencias FROM mapcartacomp.lote_etapa WHERE id = %s", (cq,))["expor_ocorrencias"]
    assert df.acao(ex, "DF", cq, "pular", OBS)["status_nacional"] == "EM_PRODUCAO"  # CQ é opcional
    # Reabrir a última concluída (a aquisição) e concluir de novo.
    aq = ex.um("SELECT id FROM mapcartacomp.lote_etapa WHERE id_lote = %s AND situacao = 'concluida'", (lote,))["id"]
    assert df.acao(ex, "DF", aq, "reabrir", OBS)["situacao"] == "em_andamento"
    assert "GCQ" in _recusa(ex, df.acao, "DF", aq, "gcq", OBS, "aprovada").mensagem


def test_editar_copiar_e_modelo(amb):
    cen, ex = amb
    fluxo = df.criar(ex, "DF", 5, cen.tema, "DF editar", [_etapa("aquisicao", conta=True, repetivel=False)])
    lote, _ = _folha(ex, "DF", fluxo)
    aq = fluxo["etapas"][0]
    # Reordena e acrescenta; a etapa com passagem não sai nem muda de fase.
    com_ativ = {**aq, "atividades": [cen.ativ["aquisicao"]]}
    f2 = df.alterar(ex, "DF", fluxo["id"], None, None, [_etapa("cq", obrigatoria=False), com_ativ])
    assert [x["fase"] for x in f2["etapas"]] == ["cq", "aquisicao"]
    assert "passagens" in _recusa(ex, df.alterar, "DF", fluxo["id"], None, None, [_etapa("cq")]).mensagem
    assert (
        "fase não muda"
        in _recusa(
            ex, df.alterar, "DF", fluxo["id"], None, None, [{**aq, "fase": "revisao", "atividades": []}]
        ).mensagem
    )
    assert _recusa(ex, df.alterar, "GO", fluxo["id"], "x", None).status == 403
    copia = df.copiar(ex, "GO", fluxo["id"], "cópia do DF")
    assert copia["uf"] == "GO" and [x["fase"] for x in copia["etapas"]] == ["cq", "aquisicao"]
    modelo = df.do_modelo(ex, "DF", 5, cen.tema, "Modelo CCAR")
    assert [x["fase"] for x in modelo["etapas"]] == [m["fase"] for m in df.MODELO_CCAR]
    aq_mod = next(x for x in modelo["etapas"] if x["fase"] == "aquisicao")
    assert [a["id"] for a in aq_mod["atividades"]] == [cen.ativ["aquisicao"]]
