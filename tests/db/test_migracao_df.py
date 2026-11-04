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
    "correção de inspeção fora da folha do rótulo",
    "FINAL: nenhuma folha tem metade da carga",
    "CORTE_M_DAGUA: nenhuma folha tem metade da carga",
    "geometria inválida ou vazia mesmo depois de corrigida",
}
# Rótulos de CQ convertidos para outra folha ou com duas passagens na mesma revisão: fora da comparação 1 a 1.
ROTULOS_CORRIGIDOS = {"2470-5", "2570-5", "2532-2", "2535-2"}


def _contar(cur):
    cur.execute(
        """
        SELECT (SELECT count(*) FROM mapcartacomp.carga_trabalho WHERE uf = 'DF'),
               (SELECT count(*) FROM mapcartacomp.cq_amostra WHERE uf = 'DF'),
               (SELECT count(*) FROM mapcartacomp.lote WHERE uf = 'DF'),
               (SELECT count(*) FROM mapcartacomp.lote_etapa WHERE uf = 'DF'),
               (SELECT count(*) FROM mapcartacomp.cq_plano WHERE uf = 'DF'),
               (SELECT count(*) FROM mapcartacomp.cq_inspecao WHERE uf = 'DF')
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
    cargas, amostras, *_ = convertido["contagens"][0]
    assert (cargas, amostras) == (c["cargas convertidas"], c["amostras convertidas"])


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
            ((cq or {}).get("Nome") or {}).get("amostras", 0),
            el(cq, "Nome"),
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
