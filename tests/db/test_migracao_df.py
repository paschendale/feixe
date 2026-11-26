"""A3: conversão do bc100ggcdf_apoio (GGC de dev) para o mapcartacomp (CCAR de dev).

A conversão roda duas vezes dentro de uma transação da CCAR que é desfeita no fim (leva alguns minutos: lê ~45 mil
cargas pela rede). Confere que nada se perde sem registro, que rodar de novo não duplica e que ctrl_lote_etapa
reproduz o ctrl_folha_revisao do sistema atual nas folhas de hidrografia.
"""

from __future__ import annotations

import pytest
from scripts.db.migrar_df import converter

from tests.db.conftest import url

pytestmark = pytest.mark.db

MOTIVOS_ESPERADOS = {
    "atividade nula",
    "referência de massa d'água (não executado)",
    "revisão X (fora da conta)",
    "demonstração (SHOW)",
    "lote de teste (u_3448274)",
    "mais da metade da área fora da folha do rótulo",
    "CQ de ADE sem amostra (planejamento incompleto)",
    "CQ sem amostra",
    "correção de inspeção fora da folha do rótulo",
    "FINAL: nenhuma folha tem metade da carga",
    "CORTE_M_DAGUA: nenhuma folha tem metade da carga",
    "geometria inválida ou vazia mesmo depois de corrigida",
}
# Rótulos de CQ convertidos para outra folha ou com duas passagens na mesma revisão: fora da comparação 1 a 1.
ROTULOS_CORRIGIDOS = {"2470-5", "2570-5", "2532-2", "2535-2"}


def _contar(cur):
    # Só o que a conversão gravou (criado pela conta que roda a conversão): cargas e folhas de teste criadas no dev
    # por outras contas ou por scripts (criado_por próprio) não entram.
    cur.execute(
        """
        SELECT (SELECT count(*) FROM mapcartacomp.carga_trabalho WHERE uf = 'DF' AND criado_por = current_user),
               (SELECT count(*) FROM mapcartacomp.cq_amostra WHERE uf = 'DF' AND criado_por = current_user),
               (SELECT count(*) FROM mapcartacomp.lote WHERE uf = 'DF' AND criado_por = current_user),
               (SELECT count(*) FROM mapcartacomp.lote_etapa WHERE uf = 'DF' AND criado_por = current_user),
               (SELECT count(*) FROM mapcartacomp.cq_plano WHERE uf = 'DF' AND criado_por = current_user),
               (SELECT count(*) FROM mapcartacomp.cq_inspecao WHERE uf = 'DF' AND criado_por = current_user)
        """
    )
    return cur.fetchone()


@pytest.fixture(scope="module")
def convertido():
    psycopg2 = pytest.importorskip("psycopg2")
    ggc = psycopg2.connect(url("FEIXE_GGC"))
    ccar = psycopg2.connect(url("FEIXE_CCAR"))
    try:
        rel = converter(ggc, ccar)
        with ccar.cursor() as cur:
            primeira = _contar(cur)
        rel2 = converter(ggc, ccar)
        with ccar.cursor() as cur:
            segunda = _contar(cur)
        yield {"ggc": ggc, "ccar": ccar, "rel": rel, "rel2": rel2, "contagens": (primeira, segunda)}
    finally:
        ccar.rollback()
        ccar.close()
        ggc.close()


def test_nada_se_perde_sem_registro(convertido):
    rel = convertido["rel"]
    c = rel.contagens
    assert c["cargas convertidas"] + c["cargas ignoradas"] == c["cargas na origem"]
    assert c["amostras convertidas"] + sum(rel.amostras_ignoradas.values()) == c["amostras na origem"]
    assert set(rel.ignoradas) <= MOTIVOS_ESPERADOS, set(rel.ignoradas) - MOTIVOS_ESPERADOS
    # Uma carga por amostra no CQ: cada carga de CQ convertida tem exatamente uma amostra.
    cargas, amostras, *_ = convertido["contagens"][0]
    assert (cargas, amostras) == (c["cargas gravadas"], c["amostras convertidas"])
    with convertido["ccar"].cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.uf = 'DF' AND c.id_cq_plano IS NOT NULL "
            "AND (SELECT count(*) FROM mapcartacomp.cq_amostra a WHERE a.id_carga_trabalho = c.id) <> 1"
        )
        assert cur.fetchone()[0] == 0


def test_rodar_de_novo_nao_duplica(convertido):
    primeira, segunda = convertido["contagens"]
    assert primeira == segunda
    assert convertido["rel"].contagens == convertido["rel2"].contagens


def test_folhas_viram_lotes_por_tema(convertido):
    """Toda folha com carga convertida de aquisição vira um lote do tema (a mesma folha aparece em vários temas)."""
    ignoradas = [i for ids in convertido["rel"].ignoradas.values() for i in ids]
    with convertido["ggc"].cursor() as cur:
        cur.execute(
            """
            SELECT CASE id_atividade WHEN 1 THEN 'Hidrografia' WHEN 11 THEN 'Áreas densamente edificadas'
                   ELSE 'LML' END, split_part(folha_revisao, '-', 1)
              FROM bc100ggcdf_apoio.carga_trabalho
             WHERE id_atividade IN (1, 11, 21) AND folha_revisao ~ '^\\d{4}-\\d+$' AND id_carga_trabalho <> ALL(%s)
             GROUP BY 1, 2
            """,
            (ignoradas,),
        )
        esperado = set(cur.fetchall())
    with convertido["ccar"].cursor() as cur:
        cur.execute(
            "SELECT t.nome, l.nome FROM mapcartacomp.lote l JOIN mapcartacomp.tema t ON t.id = l.id_tema "
            "WHERE l.uf = 'DF' AND l.tipo = 'folha'"
        )
        lotes = set(cur.fetchall())
        cur.execute(
            "SELECT count(*) FROM mapcartacomp.lote "
            "GROUP BY cod_projeto, id_tema, id_articulacao_scn HAVING count(*) > 1"
        )
        assert cur.fetchall() == []
    assert esperado <= lotes, esperado - lotes
    assert {t for t, _ in lotes} == {"Hidrografia", "Áreas densamente edificadas", "LML"}


def test_ctrl_lote_reproduz_ctrl_folha_revisao(convertido):
    """Percentual de revisão, número de amostras e avaliações por elemento iguais aos do sistema atual."""
    ignoradas = [i for ids in convertido["rel"].ignoradas.values() for i in ids]
    with convertido["ggc"].cursor() as cur:
        cur.execute(
            "SELECT DISTINCT folha_revisao FROM bc100ggcdf_apoio.carga_trabalho WHERE id_carga_trabalho = ANY(%s)",
            (ignoradas,),
        )
        excluir = {r[0] for r in cur.fetchall()} | ROTULOS_CORRIGIDOS
        cur.execute(
            """
            SELECT folha_revisao, rev_porcentagem_conclusao, cq_n_amostras,
                   cq_amostra_nome_aprovadas, cq_amostra_nome_reprovadas, cq_amostra_nome_pendentes,
                   cq_amostra_omissao_aprovadas, cq_amostra_omissao_reprovadas, cq_amostra_omissao_pendentes,
                   cq_amostra_comissao_aprovadas, cq_amostra_comissao_reprovadas, cq_amostra_comissao_pendentes
              FROM bc100ggcdf_apoio.ctrl_folha_revisao WHERE folha_revisao ~ '^\\d{4}-\\d+$'
            """
        )
        atual = {r[0]: r[1:] for r in cur.fetchall() if r[0] not in excluir}

    def el(cq, nome):
        e = (cq or {}).get(nome) or {}
        return (e.get("conformes", 0), e.get("nao_conformes", 0), e.get("pendentes", 0))

    with convertido["ccar"].cursor() as cur:
        cur.execute(
            """
            SELECT folha_revisao, fase, perc_concluidas, cq_por_elemento
              FROM mapcartacomp.ctrl_lote_etapa WHERE uf = 'DF' AND tema = 'Hidrografia' AND fase IN ('aquisicao', 'cq')
            """
        )
        novo = {}
        for rotulo, fase, perc, cq in cur.fetchall():
            d = novo.setdefault(rotulo, {"perc": None, "cq": None})
            if fase == "aquisicao":
                d["perc"] = perc
            else:
                d["cq"] = cq
    comparadas, diferentes = 0, []
    for rotulo, r in atual.items():
        n = novo.get(rotulo)
        if n is None:
            diferentes.append((rotulo, "ausente"))
            continue
        cq = n["cq"]
        esperado = (r[0], r[1] or 0, r[2:5], r[5:8], r[8:11])
        obtido = (
            n["perc"],
            ((cq or {}).get("Nome Geográfico") or {}).get("amostras", 0),
            el(cq, "Nome Geográfico"),
            el(cq, "Omissão"),
            el(cq, "Comissão"),
        )
        esperado = (esperado[0], esperado[1], *(tuple(x or 0 for x in t) for t in esperado[2:]))
        if esperado != obtido:
            diferentes.append((rotulo, esperado, obtido))
        comparadas += 1
    print(f"\nctrl_lote_etapa x ctrl_folha_revisao: {comparadas} folhas-revisão de hidrografia comparadas")
    assert not diferentes, diferentes[:5]
    assert comparadas >= 5


def test_cq_tem_uma_atividade_e_um_plano_por_medida(convertido):
    """CQ do DF: atividade por tema + medida; cada passagem tem no máximo um plano por atividade, do tamanho n."""
    with convertido["ccar"].cursor() as cur:
        cur.execute(
            "SELECT t.nome, m.nome FROM mapcartacomp.fluxo f JOIN mapcartacomp.tema t ON t.id = f.id_tema "
            "JOIN mapcartacomp.fluxo_etapa fe ON fe.id_fluxo = f.id "
            "JOIN mapcartacomp.fluxo_etapa_atividade fa ON fa.id_fluxo_etapa = fe.id "
            "JOIN mapcartacomp.atividade a ON a.id = fa.id_atividade "
            "JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = a.id_medidadequalidade "
            "WHERE f.uf = 'DF' AND fe.fase = 'cq'"
        )
        assert set(cur.fetchall()) == {
            ("Hidrografia", "Nome Geográfico"),
            ("Hidrografia", "Omissão"),
            ("Hidrografia", "Comissão"),
            ("Áreas densamente edificadas", "Omissão"),
            ("Áreas densamente edificadas", "Acurácia Temporal"),
            ("Áreas densamente edificadas", "Comissão"),
            ("Áreas densamente edificadas", "Consistência Topológica"),
        }
        cur.execute(
            "SELECT count(*) FROM (SELECT id_lote_etapa, id_atividade FROM mapcartacomp.cq_plano WHERE uf = 'DF' "
            "GROUP BY 1, 2 HAVING count(*) > 1) s"
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM mapcartacomp.cq_plano p WHERE p.uf = 'DF' AND p.tamanho_amostra_n <> "
            "(SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.id_cq_plano = p.id)"
        )
        assert cur.fetchone()[0] == 0


def test_cq_do_df_tem_o_padrao_dos_planos(convertido):
    """D-135: a etapa de CQ dos fluxos do DF sai com nível II, LQA 2,5% e fração crítica 2,5%; as outras, sem padrão."""
    with convertido["ccar"].cursor() as cur:
        cur.execute(
            "SELECT fe.fase = 'cq', fe.nivel_inspecao, fe.lqa::float8, fe.fracao_critica::float8 "
            "FROM mapcartacomp.fluxo f JOIN mapcartacomp.fluxo_etapa fe ON fe.id_fluxo = f.id WHERE f.uf = 'DF'"
        )
        linhas = cur.fetchall()
    assert {(n, lqa, fc) for cq, n, lqa, fc in linhas if cq} == {("II", 2.5, 2.5)}
    assert {(n, lqa, fc) for cq, n, lqa, fc in linhas if not cq} == {(None, None, None)}
