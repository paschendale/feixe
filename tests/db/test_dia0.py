"""D-109: o caminho do supervisor sem passos vazios. A folha nova (e a etapa aberta) já sai com as cargas; distribuir
inicia a etapa; uma folha por pessoa, o resto na fila; a próxima etapa em várias folhas, com prévia. Transações
desfeitas."""

from __future__ import annotations

import uuid

import psycopg2.extras
import pytest
from feixe.core.dados import ExecutorPg
from feixe.core.dados import cargas as dc
from feixe.core.dados import filas as dfi
from feixe.core.dados import fluxos as df

from tests.db.migracoes import aplicar
from tests.db.test_atribuir import _conta
from tests.db.test_regras import Cenario

pytestmark = pytest.mark.db


@pytest.fixture
def amb(banco):
    aplicar(banco)
    with banco.cursor() as cur, banco.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as dcur:
        cen = Cenario(cur)
        cur.execute(
            "UPDATE mapcartacomp.atividade SET geracao = 'grade', grade_nivel = 5000 WHERE id = %s",
            (cen.ativ["aquisicao"],),
        )
        cur.execute(
            "UPDATE mapcartacomp.atividade SET geracao = 'amostra_area', grade_nivel = 5000 WHERE id = ANY(%s)",
            (list(cen.ativ_cq.values()),),
        )
        # Uma etapa sem atividade (como a revisão do modelo da CCAR), entre a aquisição e o CQ.
        cur.execute(
            "UPDATE mapcartacomp.fluxo_etapa SET ordem = ordem + 10 WHERE id_fluxo = %s AND ordem > 1", (cen.fluxo,)
        )
        cur.execute(
            "INSERT INTO mapcartacomp.fluxo_etapa (id_fluxo, ordem, fase, nome, repetivel) "
            "VALUES (%s, 2, 'revisao', 'Revisão sem atividade', true) RETURNING id",
            (cen.fluxo,),
        )
        cen.etapa["revisao"] = cur.fetchone()[0]
        for conta in ("t_apm_a", "t_apm_b", "t_apm_c"):
            _conta(cur, conta)
        _conta(cur, "t_aval", perfil="V")
        yield cen, ExecutorPg(dcur)


def _livre(cen, nome, x0, situacao="pendente", fase="aquisicao"):
    """Lote livre de meio grau, na mesma área da 2534, com a passagem na fase pedida."""
    cen.cur.execute(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome, geom) "
        "VALUES (%s, 5, %s, %s, 'DF', 'livre', %s, ST_Multi(ST_MakeEnvelope(%s, -20.5, %s, -20, 4674))) RETURNING id",
        (str(uuid.uuid4()), cen.tema, cen.fluxo, nome, x0, x0 + 0.5),
    )
    lote = cen.cur.fetchone()[0]
    cen.cur.execute(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, situacao, iniciada_em) "
        "VALUES (%s, %s, %s, %s, CASE WHEN %s <> 'pendente' THEN now() END) RETURNING id",
        (str(uuid.uuid4()), lote, cen.etapa[fase], situacao, situacao),
    )
    return lote, cen.cur.fetchone()[0]


def _situacao(ex, le):
    return ex.um("SELECT situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))["situacao"]


def _hist(ex, le):
    return [
        r["acao"]
        for r in ex.todos("SELECT acao FROM mapcartacomp.lote_etapa_hist WHERE id_lote_etapa = %s ORDER BY id", (le,))
    ]


def test_preparar_gera_em_lote_inicia_sem_atividade_e_avisa_o_cq(amb):
    cen, ex = amb
    folha = cen.passagem("aquisicao")
    _, livre = _livre(cen, "livre", -44.5)
    _, revisao = _livre(cen, "revisão", -44.5, fase="revisao")
    _, cq = _livre(cen, "cq", -44.5, fase="cq")
    esperado = {le: dc.gerar_pela_grade(ex, le, True)["celulas"] for le in (folha, livre)}

    r = dc.preparar(ex, "DF", [folha, livre, revisao, cq])
    assert {g["id_lote_etapa"]: g["gravadas"] for g in r["geradas"]} == esperado
    for le, n in esperado.items():
        assert ex.um("SELECT count(*) AS n FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s", (le,))["n"] == n
        assert _situacao(ex, le) == "pendente"  # tem cargas: começa quando alguém as receber
    assert [i["id_lote_etapa"] for i in r["iniciadas"]] == [revisao]
    assert _situacao(ex, revisao) == "em_andamento" and _hist(ex, revisao) == ["iniciar"]
    assert [a["id_lote_etapa"] for a in r["avisos"]] == [cq] and "amostragem" in r["avisos"][0]["aviso"]
    # De novo não duplica nada, e passagem de outra unidade fica de fora.
    assert dc.preparar(ex, "DF", [folha, livre, revisao]) == {"geradas": [], "iniciadas": [], "avisos": []}
    assert dc.preparar(ex, "GO", [cq])["avisos"] == []


def test_distribuir_cargas_inicia_a_etapa(amb):
    cen, ex = amb
    _, le = _livre(cen, "a distribuir", -44.5)
    dc.preparar(ex, "DF", [le])
    dc.atribuir(ex, "DF", None, lote_etapas=[le])  # devolver não começa nada
    assert _situacao(ex, le) == "pendente"
    dc.atribuir(ex, "DF", "t_apm_a", lote_etapas=[le])
    assert _situacao(ex, le) == "em_andamento" and _hist(ex, le) == ["iniciar"]
    dc.atribuir(ex, "DF", "t_apm_b", lote_etapas=[le])  # já em andamento: nada a mais no histórico
    assert _hist(ex, le) == ["iniciar"]


def test_uma_folha_por_pessoa_e_a_revisao_as_cegas(amb):
    cen, ex = amb
    lotes = [_livre(cen, f"f{i}", -44.5) for i in range(4)]
    dc.preparar(ex, "DF", [le for _, le in lotes])
    s = dfi.sugestao(ex, "DF", [lt for lt, _ in lotes])
    sugeridas = [f["sugerida"] for f in s["folhas"]]
    # Perfil O na aquisição (o avaliador fica de fora) e uma folha por pessoa antes de repetir alguém.
    operadores = [p for p in s["pessoas"] if ":O" in (p["perfis"] or "")]
    assert "t_aval" not in sugeridas and "t_aval" in {p["conta"] for p in s["pessoas"]}
    assert len(set(sugeridas)) == min(4, len(operadores))

    quem = ["t_apm_a", "t_apm_b", "t_apm_c", "t_apm_a"]
    feitos = [dfi.distribuir_uma(ex, "DF", f["id_lote_etapa"], c) for f, c in zip(s["folhas"], quem)]
    assert [bool(r["atribuida"]) for r in feitos] == [True, True, True, False]  # a quarta vai para a fila de A
    assert all(_situacao(ex, f["id_lote_etapa"]) == "em_andamento" for f in s["folhas"][:3])
    quarta = s["folhas"][3]
    assert _situacao(ex, quarta["id_lote_etapa"]) == "pendente"
    # Trocar a pessoa da folha que está na fila tira da fila antiga; quem está livre recebe na hora.
    _conta(cen.cur, "t_apm_d")
    assert dfi.distribuir_uma(ex, "DF", quarta["id_lote_etapa"], "t_apm_d")["atribuida"]
    assert dfi.listar(ex, "DF")["itens"] == []

    # Na etapa seguinte da mesma folha, quem fez a anterior não é sugerido, se há outra pessoa.
    lote, le = lotes[0]
    feito_por = "t_apm_a"
    ex.executar("UPDATE mapcartacomp.carga_trabalho SET concluido = true WHERE id_lote_etapa = %s", (le,))
    df.acao(ex, "DF", le, "concluir", "aquisição conferida")
    nova = df.nova_passagem(ex, "DF", lote, cen.etapa["aquisicao"], "aquisição de novo, por outra pessoa")
    assert dc.preparar(ex, "DF", [nova["id_lote_etapa"]])["geradas"]
    assert dfi.sugestao(ex, "DF", [lote])["folhas"][0]["sugerida"] not in (feito_por, None)


def test_proxima_etapa_em_varias_folhas(amb):
    cen, ex = amb
    feita, le1 = _livre(cen, "pronta", -44.5, "em_andamento")
    a_iniciar, _ = _livre(cen, "a iniciar", -44.5)
    terminou, le3 = _livre(cen, "terminada", -44.5, "em_andamento")
    df.acao(ex, "DF", le3, "concluir", "terminou")
    dc.preparar(ex, "DF", [le1])

    previa = {i["id_lote"]: i for i in df.avancar(ex, "DF", [feita, a_iniciar, terminou], None, True)["itens"]}
    assert previa[feita]["concluir"] and previa[feita]["proxima"] == "Revisão sem atividade"
    assert previa[feita]["pendentes"] == previa[feita]["cargas"] > 0  # o diálogo avisa: cargas pendentes
    assert not previa[terminou]["concluir"] and previa[terminou]["proxima"] == "Revisão sem atividade"
    assert "ainda não começou" in previa[a_iniciar]["erro"]
    assert _situacao(ex, le1) == "em_andamento"  # a prévia não muda nada

    r = df.avancar(ex, "DF", [feita, a_iniciar, terminou], "seguem para a revisão", False)
    assert sorted(a["id_lote"] for a in r["abertas"]) == sorted([feita, terminou])
    assert [e["id_lote"] for e in r["erros"]] == [a_iniciar]
    assert _situacao(ex, le1) == "concluida" and _hist(ex, le1) == ["concluir"]
    # A revisão não tem atividade: preparar a inicia.
    novas = [a["id_lote_etapa"] for a in r["abertas"]]
    assert sorted(i["id_lote_etapa"] for i in dc.preparar(ex, "DF", novas)["iniciadas"]) == sorted(novas)


def test_achados_do_dia0_fila_rotulo_e_cargas_no_mar(amb):
    from feixe.core.dados import lotes as dl
    from feixe.core.dados import painel as dp

    cen, ex = amb
    lote, le = _livre(cen, "litoral", -44.5)
    dc.preparar(ex, "DF", [le])
    # Antes de começar, a folha já mostra a revisão da passagem aberta (não a 0 da revisão atual).
    rotulo = ex.um("SELECT mapcartacomp.f_rotulo(tipo, nome, 1) AS r FROM mapcartacomp.lote WHERE id = %s", (lote,))[
        "r"
    ]
    assert dl.um(ex, lote)["folha_revisao"] == rotulo

    # Na fila de alguém (que ainda tem o que fazer): as cargas contam como "na fila", não como sem dono.
    _, outra = _livre(cen, "ocupada", -44.5)
    dc.preparar(ex, "DF", [outra])
    dfi.distribuir_uma(ex, "DF", outra, "t_apm_a")
    dfi.distribuir_uma(ex, "DF", le, "t_apm_a")
    linha = next(x for x in dp.supervisao(ex, "DF")["lotes"] if x["id_lote"] == lote)
    assert linha["a_atribuir"] == 0 and linha["na_fila"] > 0 and linha["fila_de"] == "Teste t_apm_a"

    # Tirar as cargas sobre o mar: só as não concluídas, de etapa aberta.
    ids = [
        r["id"]
        for r in ex.todos("SELECT id FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s ORDER BY id", (le,))
    ]
    ex.executar(
        "UPDATE mapcartacomp.carga_trabalho SET concluido = true, responsavel = 't_apm_b' WHERE id = %s", (ids[0],)
    )
    r = dc.descartar(ex, "DF", ids[:3])
    assert (r["tiradas"], r["ficaram"], r["lote_etapas"]) == (2, 1, [le])
    assert dc.descartar(ex, "GO", ids[3:4])["tiradas"] == 0
