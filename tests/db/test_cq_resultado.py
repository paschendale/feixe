"""D4: resultado do plano e da passagem de CQ, e a decisão do supervisor (Aprovar ou Nova revisão), com a observação e
o resultado por elemento no histórico. Transações desfeitas, nos dois bancos.

Cenário (`test_regras.Cenario`): aquisição (conta revisão, repetível) > CQ > correção de inspeção > envio à GCQ, na
folha 2534; a aquisição gera cargas pela grade de 5 km e as atividades de CQ planejam por área com o padrão da etapa
(nível II, LQA 4%: N em torno de 112, letra F, n=20, Ac=2).
"""

from __future__ import annotations

import uuid

import psycopg2.extras
import pytest
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import cargas as dc
from feixe.core.dados import cq as dq
from feixe.core.dados import fluxos as df
from feixe.core.dados import painel as dp

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
            "UPDATE mapcartacomp.atividade SET geracao = 'amostra_area', grade_nivel = 5000 WHERE id = ANY(%s)",
            (list(cen.ativ_cq.values()),),
        )
        cur.execute(
            "UPDATE mapcartacomp.atividade SET geracao = 'grade', grade_nivel = 5000 WHERE id = %s",
            (cen.ativ["aquisicao"],),
        )
        cur.execute(
            "UPDATE mapcartacomp.fluxo_etapa SET nivel_inspecao = 'II', lqa = 4 WHERE id = %s", (cen.etapa["cq"],)
        )
        _conta(cur, "t_apm_a")
        _conta(cur, "t_apm_b")
        yield cen, ExecutorPg(dcur)


def _folha_avaliada(cen, ex, lote=None, nao_conformes=None):
    """Aquisição da revisão 1 feita por t_apm_a e o CQ aberto, com os planos do padrão e as amostras avaliadas:
    `nao_conformes` = {medida: quantas}, as outras conformes; medida ausente fica sem avaliar."""
    lote = lote or cen.lote
    le_aq = _passagem(cen, lote, "aquisicao", "concluida")
    cen.cur.execute(
        "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, responsavel, geom, concluido) "
        "SELECT %s, %s, %s, 't_apm_a', ST_Multi(ST_Buffer(ST_Centroid(ar.geom), 0.01)), true FROM mapcartacomp.lote l "
        "JOIN mapcartctrl.t_articulacao_scn ar ON ar.id_articulacao_scn = l.id_articulacao_scn "
        "WHERE l.id = %s",
        (str(uuid.uuid4()), le_aq, cen.ativ["aquisicao"], lote),
    )
    le_cq = _passagem(cen, lote, "cq", "pendente")
    r = dc.preparar(ex, "DF", [le_cq])
    assert r["geradas"] and r["geradas"][0]["planos"] == 3
    cen.mudar(le_cq, "em_andamento")
    _avaliar(ex, le_cq, nao_conformes or {})
    return le_aq, le_cq


def _passagem(cen, lote, fase, situacao):
    cen.cur.execute(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, instancia, situacao, iniciada_em, "
        "concluida_em) SELECT %s, %s, %s, coalesce(max(instancia), 0) + 1, %s, clock_timestamp(), "
        "CASE WHEN %s = 'concluida' THEN clock_timestamp() END FROM mapcartacomp.lote_etapa "
        "WHERE id_lote = %s AND id_fluxo_etapa = %s RETURNING id",
        (str(uuid.uuid4()), lote, cen.etapa[fase], situacao, situacao, lote, cen.etapa[fase]),
    )
    return cen.cur.fetchone()[0]


def _avaliar(ex, le_cq, nao_conformes, todas=True):
    """Avalia as amostras de cada plano: as primeiras `nao_conformes[medida]` não conformes, as outras conformes. Com
    `todas=False`, deixa a última amostra de cada plano sem avaliar."""
    for p in ex.todos(
        "SELECT p.id, m.nome::text AS medida FROM mapcartacomp.cq_plano p "
        "JOIN mapcartacomp.atividade a ON a.id = p.id_atividade "
        "JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = a.id_medidadequalidade WHERE p.id_lote_etapa = %s",
        (le_cq,),
    ):
        ids = [r["id"] for r in ex.todos(
            "SELECT id FROM mapcartacomp.cq_amostra WHERE id_cq_plano = %s ORDER BY id", (p["id"],))]  # fmt: skip
        if not todas:
            ids = ids[:-1]
        k = nao_conformes.get(p["medida"], 0)
        for i, a in enumerate(ids):
            ex.executar("UPDATE mapcartacomp.cq_amostra SET status = %s WHERE id = %s", (0 if i < k else 1, a))


def _hist(ex, le):
    return ex.todos(
        "SELECT acao, observacao FROM mapcartacomp.lote_etapa_hist WHERE id_lote_etapa = %s ORDER BY id", (le,)
    )


def test_plano_com_3_nao_conformes_e_ac_2_reprovado(amb):
    cen, ex = amb
    _, le_cq = _folha_avaliada(cen, ex, nao_conformes={"Comissão": 3})
    res = dq.resultados(ex, [le_cq])[le_cq]
    assert res["resultado"] == "reprovado" and res["faltam"] == 0
    com = next(p for p in res["planos"] if p["elemento"] == "Comissão")
    assert (com["n"], com["ac"], com["avaliadas"], com["nao_conformes"]) == (20, 2, 20, 3)
    assert com["resultado"] == "reprovado" and com["excede"]
    assert com["frase"] == "Comissão: 3 não conformes, aceita até 2"
    # Coerente com o banco: a coluna derivada é a da função f_cq_plano_resultado.
    assert ex.um("SELECT mapcartacomp.f_cq_plano_resultado(%s, 2) AS r", (com["id"],))["r"] == "reprovado"
    # Nível de conformidade (D-62): 3 de 20 = 15% contra a fração crítica gravada no plano (a do elemento, 4%).
    assert com["conformidade"]["observado"] == 15.0 and com["conformidade"]["fracao_critica"] == 4.0
    assert com["conformidade"]["situacao"] == "acima"
    assert "15% de não conformes nas 20 avaliadas, fração crítica 4%" in com["conformidade"]["leitura"]
    omi = next(p for p in res["planos"] if p["elemento"] == "Omissão")
    assert omi["resultado"] == "aprovado" and omi["frase"] == "Omissão: 0 não conformes, aceita até 2"

    um = dq.plano(ex, "DF", com["id"])  # GET /api/cq_planos/{id}
    assert um["resultado"] == "reprovado" and um["folha_revisao"] == "2534-1"
    with pytest.raises(ErroDados):
        dq.plano(ex, "GO", com["id"])

    # Na gaveta (GET /api/lote_etapas/{id}/cq_planos), o mesmo resultado.
    assert dq.planos(ex, "DF", le_cq)["resultado"]["resultado"] == "reprovado"

    # Esperando você: a folha avaliada aparece com o resultado e a frase por elemento.
    (g,) = [g for g in dp.esperando(ex, "DF") if g["tema"] == "teste_regras"]
    assert (g["fase"], g["resultado"]) == ("cq", "reprovado")
    (folha,) = g["folhas"]
    assert "Comissão: 3 não conformes, aceita até 2" in folha["cq"]["frase"]


def test_avaliacao_parcial_nao_fica_pronta(amb):
    cen, ex = amb
    le_aq = _passagem(cen, cen.lote, "aquisicao", "concluida")
    le_cq = _passagem(cen, cen.lote, "cq", "pendente")
    dc.preparar(ex, "DF", [le_cq])
    cen.mudar(le_cq, "em_andamento")
    _avaliar(ex, le_cq, {"Comissão": 3}, todas=False)
    res = dq.resultados(ex, [le_cq])[le_cq]
    # Plano ainda com amostra sem avaliar é pendente, mesmo com os não conformes já acima do Ac (o aviso vem em excede).
    assert res["resultado"] == "pendente" and res["faltam"] == 3 and res["sem_avaliador"] == 3
    com = next(p for p in res["planos"] if p["elemento"] == "Comissão")
    assert com["resultado"] == "pendente" and com["excede"]
    assert com["frase"] == "Comissão: 3 não conformes, aceita até 2 (19 de 20 avaliadas)"
    assert not [g for g in dp.esperando(ex, "DF") if g["tema"] == "teste_regras"]
    # Abrir a próxima pelo caminho geral não encerra o CQ: ele termina pela decisão sobre o resultado.
    (item,) = df.avancar(ex, "DF", [cen.lote], None, True)["itens"]
    assert "Aprovar ou Nova revisão" in item["erro"]
    # A prévia da decisão avisa o que falta.
    (p,) = df.previa_cq(ex, "DF", [cen.lote], "aprovar")["itens"]
    assert p["erro"] is None and "faltam avaliar 3 amostras" in p["aviso"]
    assert le_aq


def test_aprovar_reprovada_so_com_confirmacao_e_abre_a_proxima(amb):
    cen, ex = amb
    _, le_cq = _folha_avaliada(cen, ex, nao_conformes={"Comissão": 3})
    (p,) = df.previa_cq(ex, "DF", [cen.lote], "aprovar")["itens"]
    assert p["resultado"] == "reprovado" and p["proxima"] == "Etapa correcao_inspecao" and "confirmação" in p["aviso"]
    with pytest.raises(ErroDados, match="confirme"):
        df.decidir_cq(ex, "DF", cen.lote, "aprovar", "conferido com o avaliador")
    d = df.decidir_cq(ex, "DF", cen.lote, "aprovar", "comissão em área urbana, aceito", forcar=True)
    le = ex.um("SELECT situacao, resultado, concluida_em FROM mapcartacomp.lote_etapa WHERE id = %s", (le_cq,))
    assert (le["situacao"], le["resultado"]) == ("concluida", "aprovada") and le["concluida_em"]
    (h,) = [h for h in _hist(ex, le_cq) if h["acao"] == "cq_aprovada"]
    assert h["observacao"].startswith("Aprovada no CQ pelo supervisor, apesar de reprovada: ")
    assert "Comissão 3 de 20 (aceita até 2)" in h["observacao"]
    assert h["observacao"].endswith("comissão em área urbana, aceito")
    nova = ex.um(
        "SELECT le.situacao, fe.fase FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.fluxo_etapa fe "
        "ON fe.id = le.id_fluxo_etapa WHERE le.id = %s",
        (d["id_lote_etapa_nova"],),
    )
    assert nova == {"situacao": "pendente", "fase": "correcao_inspecao"}
    # Decidido não se decide de novo.
    with pytest.raises(ErroDados):
        df.decidir_cq(ex, "DF", cen.lote, "nova_revisao", "de novo")


def test_aprovada_abre_a_proxima(amb):
    cen, ex = amb
    _, le_cq = _folha_avaliada(cen, ex, nao_conformes={"Comissão": 1})
    assert dq.resultados(ex, [le_cq])[le_cq]["resultado"] == "aprovado"
    (p,) = df.previa_cq(ex, "DF", [cen.lote], "aprovar")["itens"]
    assert p["aviso"] is None and p["erro"] is None
    d = df.decidir_cq(ex, "DF", cen.lote, "aprovar", "dentro do aceito")
    assert d["proxima"] == "Etapa correcao_inspecao" and d["id_lote_etapa_nova"]
    (h,) = [h for h in _hist(ex, le_cq) if h["acao"] == "cq_aprovada"]
    assert h["observacao"].startswith("Aprovada no CQ: ") and "Comissão 1 de 20 (aceita até 2)" in h["observacao"]
    assert df.estado(ex, cen.lote)["etapa"] == "Etapa correcao_inspecao"


@pytest.mark.parametrize("expor", [False, True])
def test_nova_revisao_abre_a_revisao_seguinte_com_cargas(amb, expor):
    cen, ex = amb
    _, le_cq = _folha_avaliada(cen, ex, nao_conformes={"Comissão": 3})
    (p,) = df.previa_cq(ex, "DF", [cen.lote], "nova_revisao")["itens"]
    assert (p["proxima"], p["nova_folha"], p["autores"]) == ("Etapa aquisicao", "2534-2", ["Teste t_apm_a"])
    d = df.decidir_cq(ex, "DF", cen.lote, "nova_revisao", "comissão acima do aceito", expor=expor)
    le = ex.um("SELECT resultado FROM mapcartacomp.lote_etapa WHERE id = %s", (le_cq,))
    assert le["resultado"] == "reprovada"
    (h,) = [h for h in _hist(ex, le_cq) if h["acao"] == "cq_reprovada"]
    assert h["observacao"].startswith("Reprovada no CQ: ") and "Comissão 3 de 20" in h["observacao"]
    nova = ex.um(
        "SELECT le.revisao, le.instancia, le.situacao, le.expor_ocorrencias, fe.fase, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS rotulo FROM mapcartacomp.lote_etapa le "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "WHERE le.id = %s",
        (d["id_lote_etapa_nova"],),
    )
    assert nova == {"revisao": 2, "instancia": 2, "situacao": "pendente", "expor_ocorrencias": expor,
                    "fase": "aquisicao", "rotulo": "2534-2"}  # fmt: skip
    # As cargas saem como em todo abrir (a rota chama `preparar`), e a sugestão do Distribuir evita quem fez a anterior.
    r = dc.preparar(ex, "DF", [d["id_lote_etapa_nova"]])
    assert r["geradas"] and r["geradas"][0]["gravadas"] > 50
    from feixe.core.dados import filas as dfi

    (s,) = dfi.sugestao(ex, "DF", [cen.lote])["folhas"]
    assert "t_apm_a" in s["anteriores"]
    if s.get("sugerida"):
        assert s["sugerida"] != "t_apm_a"


def test_cq_de_novo_depois_da_revisao_sorteia_outras_celulas(amb):
    cen, ex = amb
    _, le_cq = _folha_avaliada(cen, ex, nao_conformes={"Comissão": 3})
    sql = "SELECT id_atividade, geocodigo FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s"
    antes = {(r["id_atividade"], r["geocodigo"]) for r in ex.todos(sql, (le_cq,))}
    d = df.decidir_cq(ex, "DF", cen.lote, "nova_revisao", "reprovada")
    cen.mudar(d["id_lote_etapa_nova"], "concluida")
    le_cq2 = _passagem(cen, cen.lote, "cq", "pendente")
    dc.preparar(ex, "DF", [le_cq2])
    depois = {(r["id_atividade"], r["geocodigo"]) for r in ex.todos(sql, (le_cq2,))}
    assert len(depois) == 60 and not (antes & depois)  # cada elemento em células que ele ainda não inspecionou
    assert ex.um("SELECT revisao FROM mapcartacomp.lote_etapa WHERE id = %s", (le_cq2,))["revisao"] == 2


def test_decisao_em_lote_por_folha(amb):
    cen, ex = amb
    outra = ex.um(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
        "SELECT %s, 5, %s, %s, 'DF', 'folha', id_articulacao_scn, '2535' FROM mapcartctrl.v_articulacao_scn_100000 "
        "WHERE cd_mi = '2535' RETURNING id",
        (str(uuid.uuid4()), cen.tema, cen.fluxo),
    )["id"]
    _folha_avaliada(cen, ex, nao_conformes={"Comissão": 3})
    _folha_avaliada(cen, ex, lote=outra, nao_conformes={"Omissão": 5})
    sem_cq = ex.um(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, id_articulacao_scn, nome) "
        "SELECT %s, 5, %s, %s, 'DF', 'folha', id_articulacao_scn, '2536' FROM mapcartctrl.v_articulacao_scn_100000 "
        "WHERE cd_mi = '2536' RETURNING id",
        (str(uuid.uuid4()), cen.tema, cen.fluxo),
    )["id"]
    _passagem(cen, sem_cq, "aquisicao", "em_andamento")

    (g,) = [g for g in dp.esperando(ex, "DF") if g["tema"] == "teste_regras" and g["fase"] == "cq"]
    assert g["resultado"] == "reprovado" and {f["id_lote"] for f in g["folhas"]} == {cen.lote, outra}
    itens = {i["id_lote"]: i for i in df.previa_cq(ex, "DF", [cen.lote, outra, sem_cq], "nova_revisao")["itens"]}
    assert itens[cen.lote]["erro"] is None and itens[outra]["erro"] is None
    assert "não é de CQ" in itens[sem_cq]["erro"]
    assert itens[outra]["nova_folha"] == "2535-2"
    for i in (cen.lote, outra):
        df.decidir_cq(ex, "DF", i, "nova_revisao", "reprovadas no CQ")
    assert not [g for g in dp.esperando(ex, "DF") if g["tema"] == "teste_regras" and g["fase"] == "cq"]
    assert {df.estado(ex, i)["revisao_atual"] for i in (cen.lote, outra)} == {1}  # a 2 começa ao distribuir


def test_plano_sem_ac_mostra_sem_quebrar(amb):
    cen, ex = amb
    _, le_cq = _folha_avaliada(cen, ex, nao_conformes={"Comissão": 1})
    ex.executar("UPDATE mapcartacomp.cq_plano SET numero_aceitacao_ac = NULL, fracao_critica = NULL "
                "WHERE id_lote_etapa = %s", (le_cq,))  # fmt: skip
    res = dq.resultados(ex, [le_cq])[le_cq]
    assert res["resultado"] == "sem_ac"
    com = next(p for p in res["planos"] if p["elemento"] == "Comissão")
    assert com["frase"] == "Comissão: 1 não conforme, sem Ac no plano" and com["conformidade"]["situacao"] is None
    (p,) = df.previa_cq(ex, "DF", [cen.lote], "aprovar")["itens"]
    assert "sem Ac" in p["aviso"]
    df.decidir_cq(ex, "DF", cen.lote, "aprovar", "conferido à mão")
    (h,) = [h for h in _hist(ex, le_cq) if h["acao"] == "cq_aprovada"]
    assert h["observacao"].startswith("Aprovada no CQ (plano sem Ac): ")
