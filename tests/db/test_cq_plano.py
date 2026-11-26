"""D2: plano de amostragem do CQ na passagem, sorteio reprodutível, cargas e amostras, e os planos que saem sozinhos
ao abrir a passagem de CQ com o padrão da etapa (D-136). Transações desfeitas, nos dois bancos."""

from __future__ import annotations

import uuid

import psycopg2.extras
import pytest
from feixe.core.cq import amostragem as am
from feixe.core.dados import ErroDados, ExecutorPg
from feixe.core.dados import cargas as dc
from feixe.core.dados import cq as dq

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
        _conta(cur, "t_aval", perfil="V")
        yield cen, ExecutorPg(dcur)


def _padrao(cen, nivel="II", lqa=4, fracao=None):
    cen.cur.execute(
        "UPDATE mapcartacomp.fluxo_etapa SET nivel_inspecao = %s, lqa = %s, fracao_critica = %s WHERE id = %s",
        (nivel, lqa, fracao, cen.etapa["cq"]),
    )


def _plano(ex, le, ativ):
    return ex.um("SELECT * FROM mapcartacomp.cq_plano WHERE id_lote_etapa = %s AND id_atividade = %s", (le, ativ))


def _cargas(ex, plano):
    return ex.todos(
        "SELECT c.id, c.geocodigo, c.responsavel, c.concluido, a.id AS amostra, a.status, "
        "ST_Equals(c.geom, mapcartacomp.f_grade_celula(c.geocodigo)) AS celula_inteira "
        "FROM mapcartacomp.carga_trabalho c LEFT JOIN mapcartacomp.cq_amostra a ON a.id_carga_trabalho = c.id "
        "WHERE c.id_cq_plano = %s ORDER BY c.geocodigo",
        (plano,),
    )


def test_folha_2534_nivel_ii_lqa_4_coerente_com_o_manual(amb):
    cen, ex = amb
    le = cen.passagem("cq")
    omissao = cen.ativ_cq["Omissão"]
    previa = dq.criar_plano(ex, "DF", le, omissao, "II", "4,0", previa=True, semente=7)
    esperado = am.calcular(previa["N"], "II", 4)
    assert 105 <= previa["N"] <= 130  # 2534 em 5 km: 112 (D-79)
    assert (previa["letra"], previa["n"], previa["ac"]) == (esperado.letra, esperado.n, esperado.ac) == ("F", 20, 2)
    assert previa["previa"] and _plano(ex, le, omissao) is None  # prévia não grava

    r = dq.criar_plano(ex, "DF", le, omissao, "II", "4,0", semente=7)
    assert r["geocodigos"] == previa["geocodigos"]  # com a semente da prévia, o mesmo sorteio
    p = _plano(ex, le, omissao)
    assert (p["tamanho_lote_n"], p["nivel_inspecao"], p["letra_codigo"], p["tamanho_amostra_n"]) == (
        previa["N"], "II", "F", 20,
    )  # fmt: skip
    assert (p["numero_aceitacao_ac"], float(p["lqa"]), p["semente"], p["orientacao"]) == (2, 4.0, 7, "area")
    assert float(p["fracao_critica"]) == 4  # sem padrão na etapa: a do elemento (cq_elemento, D-75)
    cargas = _cargas(ex, p["id"])
    assert [c["geocodigo"] for c in cargas] == r["geocodigos"] and len(cargas) == 20
    assert all(c["amostra"] and c["status"] is None and c["responsavel"] is None for c in cargas)
    assert all(c["celula_inteira"] and not c["concluido"] for c in cargas)

    lista = dq.planos(ex, "DF", le)
    (feito,) = lista["planos"]
    assert (feito["N"], feito["n"], feito["ac"], feito["amostras"], feito["avaliadas"]) == (previa["N"], 20, 2, 20, 0)
    assert feito["pode_refazer"] and feito["elemento"] == "Omissão"
    assert {a["elemento"] for a in lista["sem_plano"]} == {"Nome Geográfico", "Comissão"}


def test_segunda_passagem_sorteia_outras_celulas(amb):
    cen, ex = amb
    comissao = cen.ativ_cq["Comissão"]
    le1 = cen.passagem("cq")
    r1 = dq.criar_plano(ex, "DF", le1, comissao, "II", 4, semente=42)
    cen.mudar(le1, "concluida")
    # Revisão seguinte (ou o nível III depois de aprovada no II, D-135): nova passagem da mesma etapa, mesma semente.
    le2 = cen.passagem("cq", instancia=2)
    r2 = dq.criar_plano(ex, "DF", le2, comissao, "III", 4, semente=42)
    assert r2["N"] == r1["N"] - r1["n"] and r2["ja_sorteadas"] == r1["n"]
    assert not set(r1["geocodigos"]) & set(r2["geocodigos"])
    assert "menos 20 já sorteadas" in r2["universo"]
    calc = am.calcular(r2["N"], "III", 4)
    assert (r2["letra"], r2["n"], r2["ac"]) == (calc.letra, calc.n, calc.ac)
    # Outra atividade da mesma passagem tem o seu universo inteiro (cada medida, o seu sorteio, D-83).
    outra = dq.criar_plano(ex, "DF", le2, cen.ativ_cq["Omissão"], "III", 4, previa=True, semente=42)
    assert outra["N"] == r1["N"]


def test_mesma_semente_mesmo_sorteio(amb):
    cen, ex = amb
    le = cen.passagem("cq")
    ativ = cen.ativ_cq["Nome Geográfico"]
    a = dq.criar_plano(ex, "DF", le, ativ, "II", 4, previa=True, semente=123)
    b = dq.criar_plano(ex, "DF", le, ativ, "II", 4, previa=True, semente=123)
    c = dq.criar_plano(ex, "DF", le, ativ, "II", 4, previa=True, semente=124)
    assert a["geocodigos"] == b["geocodigos"] != c["geocodigos"]
    # O universo é ordenado antes do sorteio: a ordem em que o banco devolve as células não muda nada.
    universo = [f"5KME{x}N9000" for x in range(5000, 5100)]
    assert dq.sortear(universo, 20, 9) == dq.sortear(list(reversed(universo)), 20, 9)


def test_abrir_a_passagem_de_cq_gera_planos_cargas_e_amostras(amb):
    cen, ex = amb
    _padrao(cen, "II", 2.5, 2.5)  # DF: nível II, 2,5% (D-135)
    le = cen.passagem("cq")
    r = dc.preparar(ex, "DF", [le])
    (g,) = r["geradas"]
    assert g["id_lote_etapa"] == le and g["planos"] == len(cen.ativ_cq) and r["avisos"] == []
    planos = ex.todos("SELECT * FROM mapcartacomp.cq_plano WHERE id_lote_etapa = %s", (le,))
    assert len(planos) == len(cen.ativ_cq)
    for p in planos:
        calc = am.calcular(p["tamanho_lote_n"], "II", "2.5")
        assert (p["letra_codigo"], p["tamanho_amostra_n"], p["numero_aceitacao_ac"]) == (calc.letra, calc.n, calc.ac)
        assert float(p["fracao_critica"]) == 2.5 and p["semente"]
        assert len(_cargas(ex, p["id"])) == calc.n
    assert g["gravadas"] == sum(p["tamanho_amostra_n"] for p in planos)
    # Tem cargas: começa quando alguém receber (D-109); preparar de novo não duplica.
    assert ex.um("SELECT situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))["situacao"] == "pendente"
    assert dc.preparar(ex, "DF", [le]) == {"geradas": [], "iniciadas": [], "avisos": []}
    # Distribuir as amostras inicia a etapa, como na produção.
    dc.atribuir(ex, "DF", "t_aval", lote_etapas=[le])
    assert ex.um("SELECT situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))["situacao"] == "em_andamento"


def test_etapa_sem_padrao_fica_a_iniciar_com_o_proximo_passo(amb):
    cen, ex = amb
    _padrao(cen, None, None)
    le = cen.passagem("cq")
    r = dc.preparar(ex, "DF", [le])
    assert r["geradas"] == [] and r["iniciadas"] == []
    (aviso,) = r["avisos"]
    assert aviso["cq_sem_padrao"] and "gaveta" in aviso["aviso"]
    assert ex.um("SELECT count(*) AS n FROM mapcartacomp.cq_plano WHERE id_lote_etapa = %s", (le,))["n"] == 0
    assert ex.um("SELECT situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))["situacao"] == "pendente"
    # O supervisor cria os planos com os parâmetros que escolher.
    assert len(dq.planos(ex, "DF", le)["sem_plano"]) == len(cen.ativ_cq)
    dq.criar_plano(ex, "DF", le, cen.ativ_cq["Omissão"], "I", 4)
    assert len(dq.planos(ex, "DF", le)["sem_plano"]) == len(cen.ativ_cq) - 1


def test_cq_sem_atividade_de_cq_fica_a_iniciar_e_aponta_os_fluxos(amb):
    # Etapa de CQ sem nenhuma medida no fluxo (o LML do DF no dev): nada a sortear, e começar sem amostras deixava a
    # folha "em andamento" sem nada a fazer. Fica a iniciar, com o próximo passo.
    cen, ex = amb
    cen.cur.execute("DELETE FROM mapcartacomp.fluxo_etapa_atividade WHERE id_fluxo_etapa = %s", (cen.etapa["cq"],))
    le = cen.passagem("cq")
    r = dc.preparar(ex, "DF", [le])
    assert r["geradas"] == [] and r["iniciadas"] == []
    (aviso,) = r["avisos"]
    assert "não tem atividade de CQ" in aviso["aviso"] and "Fluxos" in aviso["aviso"]
    assert ex.um("SELECT situacao FROM mapcartacomp.lote_etapa WHERE id = %s", (le,))["situacao"] == "pendente"


def test_refazer_so_antes_de_avaliar_ou_distribuir(amb):
    cen, ex = amb
    le = cen.passagem("cq")
    omissao, comissao = cen.ativ_cq["Omissão"], cen.ativ_cq["Comissão"]
    r1 = dq.criar_plano(ex, "DF", le, omissao, "II", 4, semente=1)
    with pytest.raises(ErroDados, match="refaça"):
        dq.criar_plano(ex, "DF", le, omissao, "III", 4)
    r2 = dq.criar_plano(ex, "DF", le, omissao, "III", 4, refazer=True)
    assert r2["refeito"] and r2["semente"] != r1["semente"] and r2["n"] == am.calcular(r1["N"], "III", 4).n
    assert ex.um("SELECT count(*) AS n FROM mapcartacomp.cq_plano WHERE id_lote_etapa = %s", (le,))["n"] == 1
    p = _plano(ex, le, omissao)
    assert len(_cargas(ex, p["id"])) == r2["n"]

    # Uma carga distribuída: não refaz mais.
    carga = _cargas(ex, p["id"])[0]
    dc.atribuir(ex, "DF", "t_aval", ids=[carga["id"]])
    with pytest.raises(ErroDados, match="distribuídas"):
        dq.criar_plano(ex, "DF", le, omissao, "II", 4, refazer=True, previa=True)
    assert not dq.planos(ex, "DF", le)["planos"][0]["pode_refazer"]

    # Uma amostra avaliada: também não.
    dq.criar_plano(ex, "DF", le, comissao, "II", 4)
    pc = _plano(ex, le, comissao)
    ex.executar("UPDATE mapcartacomp.cq_amostra SET status = 1 WHERE id = %s", (_cargas(ex, pc["id"])[0]["amostra"],))
    with pytest.raises(ErroDados, match="avaliadas"):
        dq.criar_plano(ex, "DF", le, comissao, "II", 4, refazer=True)


def test_recusas(amb):
    cen, ex = amb
    le = cen.passagem("cq")
    ativ = cen.ativ_cq["Omissão"]
    with pytest.raises(ErroDados, match="Nível de inspeção"):
        dq.criar_plano(ex, "DF", le, ativ, "IV", 4, previa=True)
    with pytest.raises(ErroDados, match="Quadro 6"):
        dq.criar_plano(ex, "DF", le, ativ, "II", 3, previa=True)
    with pytest.raises(ErroDados, match="fração crítica"):
        dq.criar_plano(ex, "DF", le, ativ, "II", 4, fracao_critica=120, previa=True)
    with pytest.raises(ErroDados, match="fora desta etapa"):
        dq.criar_plano(ex, "DF", le, cen.ativ["aquisicao"], "II", 4, previa=True)
    with pytest.raises(ErroDados, match="sua unidade"):
        dq.criar_plano(ex, "GO", le, ativ, "II", 4, previa=True)
    aq = cen.passagem("aquisicao", instancia=1)
    with pytest.raises(ErroDados, match="só em etapa de CQ"):
        dq.planos(ex, "DF", aq)
    cen.mudar(le, "concluida")
    with pytest.raises(ErroDados, match="encerrada"):
        dq.criar_plano(ex, "DF", le, ativ, "II", 4, previa=True)


def test_n_maior_ou_igual_a_N_inspeciona_todas(amb):
    cen, ex = amb
    # Lote livre pequeno: poucas células de 5 km com o centroide nele.
    cen.cur.execute(
        "INSERT INTO mapcartacomp.lote (uuid, cod_projeto, id_tema, id_fluxo, uf, tipo, nome, geom) "
        "VALUES (%s, 5, %s, %s, 'DF', 'livre', 'pequeno', ST_Multi(ST_MakeEnvelope(-44.5, -20.1, -44.41, -20.05, "
        "4674))) RETURNING id",
        (str(uuid.uuid4()), cen.tema, cen.fluxo),
    )
    lote = cen.cur.fetchone()[0]
    cen.cur.execute(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa) VALUES (%s, %s, %s) RETURNING id",
        (str(uuid.uuid4()), lote, cen.etapa["cq"]),
    )
    le = cen.cur.fetchone()[0]
    r = dq.criar_plano(ex, "DF", le, cen.ativ_cq["Omissão"], "III", 4)
    assert 1 <= r["N"] <= 3 and r["inspecao_completa"] and r["n"] == r["N"]
    assert "no lote" in r["universo"]
    p = _plano(ex, le, cen.ativ_cq["Omissão"])
    assert len(_cargas(ex, p["id"])) == r["N"] == p["tamanho_amostra_n"]


def test_padrao_do_cq_no_fluxo(amb):
    from feixe.core.dados import fluxos as df

    cen, ex = amb
    # O modelo da CCAR já traz o padrão no CQ (nível II, LQA 4%): abrir o CQ sorteia sem passo vazio (D-136).
    f = df.do_modelo(ex, "DF", 5, cen.tema, "DF modelo CQ")
    (cq,) = [e for e in f["etapas"] if e["fase"] == "cq"]
    assert (cq["nivel_inspecao"], cq["lqa"], cq["fracao_critica"]) == ("II", 4.0, None)
    etapas = [{**e, "atividades": [a["id"] for a in e["atividades"]]} for e in f["etapas"]]
    for e in etapas:
        if e["fase"] == "cq":
            e.update(nivel_inspecao="3", lqa="2,5", fracao_critica=2.5)
    f = df.alterar(ex, "DF", f["id"], None, None, etapas)
    (cq,) = [e for e in f["etapas"] if e["fase"] == "cq"]
    assert (cq["nivel_inspecao"], cq["lqa"], cq["fracao_critica"]) == ("III", 2.5, 2.5)
    for e in etapas:
        if e["fase"] == "cq":
            e["lqa"] = 3
    with pytest.raises(ErroDados, match="Quadro 6"):
        df.alterar(ex, "DF", f["id"], None, None, etapas)
    for e in etapas:
        e.update(lqa=4 if e["fase"] == "cq" else None)
        if e["fase"] == "aquisicao":
            e["nivel_inspecao"] = "II"
    with pytest.raises(ErroDados, match="só na etapa de CQ"):
        df.alterar(ex, "DF", f["id"], None, None, etapas)


def test_copiar_fluxo_com_padrao_fora_do_manual(amb):
    from feixe.core.dados import fluxos as df

    cen, ex = amb
    _padrao(cen, "2", 4)
    f = df.copiar(ex, "DF", cen.fluxo, "cópia normalizada")
    (cq,) = [e for e in f["etapas"] if e["fase"] == "cq"]
    assert (cq["nivel_inspecao"], cq["lqa"]) == ("II", 4.0)
    _padrao(cen, "S-3", 4)  # o banco aceita texto aberto; a cópia não falha, só perde o nível
    f = df.copiar(ex, "DF", cen.fluxo, "cópia sem nível")
    (cq,) = [e for e in f["etapas"] if e["fase"] == "cq"]
    assert (cq["nivel_inspecao"], cq["lqa"]) == (None, 4.0)


def test_andamento_do_plano_e_amostras_sem_avaliador_no_painel(amb):
    """D3d: a gaveta mostra não conformes x Ac por plano; o Início, as amostras sem avaliador por atividade, fora das
    cargas de produção a atribuir (D-101); a Equipe, as pendentes do avaliador no grupo do CQ."""
    from feixe.core.dados import painel as dp

    cen, ex = amb
    le = cen.passagem("cq")
    omissao = cen.ativ_cq["Omissão"]
    antes = dp.supervisao(ex, "DF")
    producao_antes = {g["chave"]: g["a_atribuir"] for g in antes["grupos"] if g["fase"] != "cq"}
    sem_antes = {s["id_atividade"]: s["amostras"] for s in antes["amostras_sem_avaliador"]}
    dq.criar_plano(ex, "DF", le, omissao, "II", 4, semente=7)

    s = dp.supervisao(ex, "DF")
    item = next(x for x in s["amostras_sem_avaliador"] if x["id_atividade"] == omissao)
    assert item["amostras"] == sem_antes.get(omissao, 0) + 20 and item["elemento"] == "Omissão"
    assert item["chave"].startswith("cq-") and cen.lote in item["lotes"]
    assert {g["chave"]: g["a_atribuir"] for g in s["grupos"] if g["fase"] != "cq"} == producao_antes

    p = _plano(ex, le, omissao)
    cargas = _cargas(ex, p["id"])
    dc.atribuir(ex, "DF", "t_aval", ids=[c["id"] for c in cargas])
    for c, status in zip(cargas[:3], (0, 0, 1)):
        ex.executar("UPDATE mapcartacomp.cq_amostra SET status = %s WHERE id = %s", (status, c["amostra"]))
    (feito,) = dq.planos(ex, "DF", le)["planos"]
    assert (feito["avaliadas"], feito["nao_conformes"], feito["ac"]) == (3, 2, 2)

    s = dp.supervisao(ex, "DF")
    assert all(x["id_atividade"] != omissao or x["amostras"] == sem_antes.get(omissao, 0)
               for x in s["amostras_sem_avaliador"])  # fmt: skip
    aval = next(x for x in s["pessoas"] if x["conta"] == "t_aval")
    assert aval["por_grupo"] == {item["chave"]: 17} and aval["grupos"] == [item["chave"]]
