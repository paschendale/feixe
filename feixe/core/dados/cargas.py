"""Cargas de trabalho: leituras e escritas das rotas. Recebe um `Executor` (ver o pacote)."""

from __future__ import annotations

from typing import Dict, List, Optional

from .. import papeis
from . import ErroDados, Executor, cq, novo_uuid

# Passagens abertas dos lotes (pendentes ou em andamento, no máximo uma por lote): é o que o supervisor está
# distribuindo agora. Uma folha sem etapa aberta (esperando o supervisor andar) fica de fora (D-105).
SQL_PASSAGENS_ATUAIS = (
    "SELECT le.id FROM mapcartacomp.lote l JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id "
    "WHERE le.situacao IN ('pendente', 'em_andamento')"
)

ABERTAS = ("pendente", "em_andamento")
_SQL_ABERTAS = "('pendente', 'em_andamento')"


# --- Gerar cargas pela grade estatística (B4) ------------------------------------------------------------------------


def preparar(ex: Executor, uf: str, ids_lote_etapa: List[int]) -> Dict:
    """O que a passagem recém-aberta precisa sem decisão de ninguém (D-109, D-136): as cargas pela grade, se a etapa
    tem uma atividade pela grade; na etapa de CQ, um plano de amostragem por atividade com o padrão da etapa e as cargas
    das amostras (`cq.gerar_padrao`); se a etapa não tem atividade que gere cargas (nenhuma, ou só de geração "nenhuma",
    como o envio à GCQ), não há o que distribuir e ela começa já. Etapa com atividade que não é pela grade (geração
    manual), CQ sem padrão na etapa, ou passagem que já tem cargas, fica como está, com o motivo em `avisos`.

    Correção de inspeção (D5) sem atividade pela grade: uma carga só, a folha inteira, da atividade manual (ou sem
    geração definida) da etapa, sem responsável: quem a recebe pelo Distribuir varre as ocorrências da folha, e ela
    conclui sozinha quando a última é tratada (`f_correcao_derivar_um`, 006). Sem ocorrência a tratar, a etapa começa
    já; sem atividade nenhuma, também, com o aviso de que ninguém recebe a folha.

    Em lote, em poucas idas e voltas: uma leitura das passagens, uma da grade de todas, um INSERT das cargas e um das
    etapas iniciadas. Volta `geradas` (por passagem; no CQ, com `planos`), `iniciadas` (sem atividade) e `avisos` (as
    que ficaram sem cargas, com o motivo)."""
    if not ids_lote_etapa:
        return {"geradas": [], "iniciadas": [], "avisos": []}
    ps = ex.todos(
        "SELECT le.id, le.situacao, le.uf, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "fe.nome AS etapa, coalesce(l.geom, ST_Multi(ar.geom)) AS geom, "
        "fe.fase, (SELECT count(*) FROM mapcartacomp.fluxo_etapa_atividade x "
        " JOIN mapcartacomp.atividade a ON a.id = x.id_atividade "
        " WHERE x.id_fluxo_etapa = fe.id AND a.geracao <> 'nenhuma') AS atividades, "
        "(SELECT array_agg(a.id) FROM mapcartacomp.fluxo_etapa_atividade x "
        " JOIN mapcartacomp.atividade a ON a.id = x.id_atividade "
        " WHERE x.id_fluxo_etapa = fe.id AND a.geracao = 'grade' AND a.ativo AND a.grade_nivel IS NOT NULL) AS grade, "
        "(SELECT a.grade_nivel FROM mapcartacomp.fluxo_etapa_atividade x "
        " JOIN mapcartacomp.atividade a ON a.id = x.id_atividade "
        " WHERE x.id_fluxo_etapa = fe.id AND a.geracao = 'grade' AND a.ativo AND a.grade_nivel IS NOT NULL "
        " LIMIT 1) AS nivel, "
        "(SELECT count(*) FROM mapcartacomp.fluxo_etapa_atividade x JOIN mapcartacomp.atividade a "
        " ON a.id = x.id_atividade WHERE x.id_fluxo_etapa = fe.id AND a.fase = 'cq' AND a.ativo "
        " AND coalesce(a.geracao, '') <> 'nenhuma') AS cq, "
        "EXISTS (SELECT 1 FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id) AS tem_cargas, "
        # Correção de inspeção (D5): a atividade que não é pela grade (manual ou sem geração definida) e as
        # ocorrências da folha ainda não tratadas, de todas as revisões.
        "(SELECT a.id FROM mapcartacomp.fluxo_etapa_atividade x JOIN mapcartacomp.atividade a "
        " ON a.id = x.id_atividade WHERE x.id_fluxo_etapa = fe.id AND a.ativo "
        " AND coalesce(a.geracao, 'manual') = 'manual' ORDER BY a.id LIMIT 1) AS ativ_folha, "
        "(SELECT count(*) FROM mapcartacomp.cq_inspecao i WHERE i.id_lote = le.id_lote AND NOT i.tratado) "
        "AS a_tratar "
        "FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN mapcartctrl.t_articulacao_scn ar ON ar.id_articulacao_scn = l.id_articulacao_scn "
        "WHERE le.id = ANY(%s) ORDER BY folha_revisao",
        (list(ids_lote_etapa),),
    )
    gerar, iniciar, avisos, amostrar, folha = [], [], [], [], []
    for p in ps:
        if p["uf"] != uf or p["situacao"] not in ABERTAS or p["tem_cargas"]:
            continue
        if p["fase"] == "cq" and p["cq"]:
            amostrar.append(p)
        elif p["fase"] == "cq":
            # CQ sem atividade de CQ na etapa: nada a sortear, e começar sem amostras não leva a lugar nenhum. Fica a
            # iniciar, com o próximo passo (a gaveta diz o mesmo).
            avisos.append({**_ident(p), "aviso": (
                f"a etapa {p['etapa']} não tem atividade de CQ no fluxo: escolha as medidas a inspecionar em Fluxos "
                "e crie os planos na gaveta do lote"
            )})  # fmt: skip
        elif p["fase"] == "correcao_inspecao" and not p["grade"]:
            # Correção de inspeção (D5): quem varre as ocorrências é quem recebe a folha. Sem atividade pela grade, a
            # carga é a folha inteira, e ela vai a alguém pelo Distribuir de sempre; nada a tratar, a etapa começa
            # já (vai para Esperando você).
            if not p["a_tratar"]:
                if p["situacao"] == "pendente":
                    iniciar.append(dict(p, motivo="Iniciada ao abrir: nenhuma ocorrência de inspeção a tratar"))
            elif p["ativ_folha"]:
                folha.append(p)
            else:
                if p["situacao"] == "pendente":
                    iniciar.append(p)
                avisos.append({**_ident(p), "aviso": (
                    f"a etapa {p['etapa']} não tem atividade no fluxo: ninguém recebe o lote para tratar as "
                    f"{p['a_tratar']} ocorrências. Acrescente a atividade de correção de inspeção à etapa (Fluxos) "
                    "e use Gerar as cargas na gaveta"
                )})  # fmt: skip
        elif not p["atividades"]:
            if p["situacao"] == "pendente":
                iniciar.append(p)
        elif p["grade"] and len(p["grade"]) == 1:
            gerar.append(p)
        elif p["grade"]:
            avisos.append({**_ident(p), "aviso": f"a etapa {p['etapa']} tem mais de uma atividade pela grade"})
        else:
            aviso = f"as cargas de {p['etapa']} não saem da grade: inicie a etapa pela gaveta quando a equipe começar"
            avisos.append({**_ident(p), "aviso": aviso})
    geradas = []
    if gerar:
        # A grade é calculada uma vez: as células voltam com a geometria e entram por unnest, com os uuids do plugin.
        ativ = {p["id"]: p["grade"][0] for p in gerar}
        celulas = ex.todos(
            "SELECT p.id, c.geocodigo, c.geom::text AS geom "
            "FROM unnest(%s::int[], %s::int[], %s::text[]) AS p(id, nivel, geom) CROSS JOIN LATERAL "
            "mapcartacomp.f_grade_celulas(p.geom::geometry, p.nivel) c",
            ([p["id"] for p in gerar], [p["nivel"] for p in gerar], [p["geom"] for p in gerar]),
        )
        por: Dict[int, int] = {}
        for c in celulas:
            por[c["id"]] = por.get(c["id"], 0) + 1
        if celulas:
            ex.executar(
                "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, geocodigo, geom) "
                "SELECT u, le, a, g, geom::geometry FROM unnest(%s::uuid[], %s::int[], %s::int[], %s::text[], "
                "%s::text[]) AS t(u, le, a, g, geom)",
                (
                    [novo_uuid() for _ in celulas], [c["id"] for c in celulas], [ativ[c["id"]] for c in celulas],
                    [c["geocodigo"] for c in celulas], [c["geom"] for c in celulas],
                ),
            )  # fmt: skip
        for p in gerar:
            n = por.get(p["id"], 0)
            if n:
                geradas.append({**_ident(p), "gravadas": n})
            else:
                avisos.append({**_ident(p), "aviso": "nenhuma célula da grade tem o centroide dentro do lote"})
    if amostrar:
        g, a = cq.gerar_padrao(ex, amostrar)
        geradas += g
        avisos += a
    if folha:
        ex.executar(
            "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, geom) "
            "SELECT u::uuid, le, a, ST_Multi(g::geometry) FROM unnest(%s::text[], %s::int[], %s::int[], %s::text[]) "
            "AS t(u, le, a, g)",
            ([novo_uuid() for _ in folha], [p["id"] for p in folha], [p["ativ_folha"] for p in folha],
             [p["geom"] for p in folha]),
        )  # fmt: skip
        geradas += [{**_ident(p), "gravadas": 1, "ocorrencias": p["a_tratar"]} for p in folha]
    por_motivo: Dict[str, List[int]] = {}
    for p in iniciar:
        obs = p.get("motivo") or "Iniciada ao abrir: a etapa não tem atividade, não há cargas a distribuir"
        por_motivo.setdefault(obs, []).append(p["id"])
    for obs, ids in por_motivo.items():
        _iniciar(ex, ids, obs)
    iniciadas = [{**_ident(p), **({"nada_a_tratar": True} if p.get("motivo") else {})} for p in iniciar]
    return {"geradas": geradas, "iniciadas": iniciadas, "avisos": avisos}


def _ident(p: Dict) -> Dict:
    return {"id_lote_etapa": p["id"], "folha_revisao": p["folha_revisao"], "etapa": p["etapa"]}


def _iniciar(ex: Executor, ids_lote_etapa: List[int], observacao: str) -> List[int]:
    """Passa para em andamento as passagens a iniciar entre `ids_lote_etapa`, com a linha no histórico."""
    feitas = [
        r["id"]
        for r in ex.todos(
            "UPDATE mapcartacomp.lote_etapa SET situacao = 'em_andamento', iniciada_em = now() "
            "WHERE id = ANY(%s) AND situacao = 'pendente' RETURNING id",
            (list(ids_lote_etapa),),
        )
    ]
    if feitas:
        ex.executar(
            "INSERT INTO mapcartacomp.lote_etapa_hist (uuid, id_lote_etapa, acao, observacao) "
            "SELECT u::uuid, le, 'iniciar', %s FROM unnest(%s::text[], %s::int[]) AS t(u, le)",
            (observacao, [novo_uuid() for _ in feitas], feitas),
        )
    return feitas


def descartar(ex: Executor, uf: str, ids: List[int]) -> Dict:
    """Tira cargas que não deviam existir (as células sobre o mar das folhas do litoral: a grade cobre a folha inteira e
    o banco não tem o contorno da terra). Só cargas não concluídas, de passagens abertas da UF; as outras ficam e voltam
    em `ficaram`. Decisão do supervisor, a partir da seleção no QGIS."""
    if not ids:
        raise ErroDados("selecione no QGIS as cargas a tirar", 400)
    tiradas = ex.todos(
        "DELETE FROM mapcartacomp.carga_trabalho c USING mapcartacomp.lote_etapa le "
        "WHERE le.id = c.id_lote_etapa AND c.id = ANY(%s) AND c.uf = %s AND NOT c.concluido "
        f"AND le.situacao IN {_SQL_ABERTAS} RETURNING c.id, c.id_lote_etapa",
        (list(ids), uf),
    )
    return {
        "tiradas": len(tiradas),
        "ficaram": len(set(ids)) - len(tiradas),
        "lote_etapas": sorted({t["id_lote_etapa"] for t in tiradas}),
    }


# --- Equipe e atribuição (B5) ----------------------------------------------------------------------------------------
# Atribuição é do supervisor e não é transição de etapa. Mas é ela que começa o trabalho: a etapa a iniciar que recebe
# a primeira carga com dono passa a em andamento (D-109), com a linha no histórico. Só cargas pendentes de passagens
# abertas mudam de mão; carga concluída fica com quem a fez.

PERFIS_EXECUTORES = papeis.perfis_que_cobrem("O")  # O, V e S: pela hierarquia, todos executam


def equipe(ex: Executor, uf: str, cod_projeto: Optional[int] = None) -> List[Dict]:
    """Contas elegíveis (P-16) lotadas na UF com perfil de execução no projeto, e o que cada uma tem nas mãos."""
    sql = (
        "SELECT u.nom_contausuario AS conta, u.nom_usuario::text AS nome, "
        "string_agg(DISTINCT pr.nom_projeto || ':' || p.cd_perfil, ', ') AS perfis, "
        "coalesce(max(c.pendentes), 0) AS pendentes, coalesce(max(c.folhas), 0) AS folhas, max(c.ultima) AS ultima "
        "FROM mapcartctrl.t_usuario u "
        "JOIN mapcartctrl.t_prd_perfil_usuarioprojeto p ON p.cd_usuario = u.cod_usuario "
        "JOIN mapcartctrl.t_projeto pr ON pr.cod_projeto = p.cd_projeto "
        "LEFT JOIN (SELECT c.responsavel, count(*) FILTER (WHERE NOT c.concluido) AS pendentes, "
        "count(DISTINCT c.id_lote_etapa) FILTER (WHERE NOT c.concluido) AS folhas, max(c.concluido_em) AS ultima "
        "FROM mapcartacomp.carga_trabalho c JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
        "WHERE le.situacao IN ('pendente', 'em_andamento') AND c.uf = %s GROUP BY c.responsavel) c "
        "ON c.responsavel = u.nom_contausuario "
        "WHERE upper(trim(u.dsc_lotacao)) = %s AND u.ind_contaativa AND NOT coalesce(u.ind_contasistema, false) "
        "AND p.cd_perfil = ANY(%s)"
    )
    params: list = [uf, uf, list(PERFIS_EXECUTORES)]
    if cod_projeto is not None:
        sql += " AND p.cd_projeto = %s"
        params.append(cod_projeto)
    return ex.todos(sql + " GROUP BY u.nom_contausuario, u.nom_usuario ORDER BY u.nom_usuario", tuple(params))


def atribuir(
    ex: Executor,
    uf: str,
    responsavel: Optional[str],
    ids: Optional[List[int]] = None,
    lote_etapas: Optional[List[int]] = None,
    so_disponiveis: bool = False,
    de: Optional[str] = None,
) -> Dict:
    """Passa cargas para `responsavel` (None = devolve para disponível). Alvo: `ids` de cargas e/ou todas as cargas de
    `lote_etapas`; `so_disponiveis` restringe às sem responsável; `de` restringe às de uma pessoa (troca no meio)."""
    if not ids and not lote_etapas:
        raise ErroDados("escolha as cargas ou os lotes", 400)
    filtro = (
        "c.uf = %s AND NOT c.concluido AND le.situacao IN ('pendente', 'em_andamento') "
        "AND (c.id = ANY(%s) OR c.id_lote_etapa = ANY(%s))"
    )
    params: list = [uf, list(ids or []), list(lote_etapas or [])]
    if so_disponiveis:
        filtro += " AND c.responsavel IS NULL"
    if de:
        filtro += " AND c.responsavel = %s"
        params.append(de)
    if responsavel is not None:
        projetos = ex.todos(
            "SELECT DISTINCT l.cod_projeto, p.nom_projeto FROM mapcartacomp.carga_trabalho c "
            "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa JOIN mapcartacomp.lote l ON l.id = le.id_lote "
            f"JOIN mapcartctrl.t_projeto p ON p.cod_projeto = l.cod_projeto WHERE {filtro}",
            tuple(params),
        )
        aptos = {r["conta"] for p in projetos for r in equipe(ex, uf, p["cod_projeto"])}
        if projetos and responsavel not in aptos:
            raise ErroDados(
                f"{responsavel} não pode receber cargas aqui: precisa de conta ativa, lotação {uf} e perfil de "
                f"execução (O, V ou S) em {', '.join(p['nom_projeto'] for p in projetos)}"
            )
    feitas = ex.um(
        "WITH alvo AS (SELECT c.id FROM mapcartacomp.carga_trabalho c "
        f"JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa WHERE {filtro} FOR UPDATE OF c), "
        "mudou AS (UPDATE mapcartacomp.carga_trabalho c SET responsavel = %s FROM alvo "
        "WHERE c.id = alvo.id AND c.responsavel IS DISTINCT FROM %s RETURNING c.id) "
        "SELECT (SELECT count(*) FROM alvo) AS alvo, (SELECT count(*) FROM mudou) AS atribuidas",
        tuple(params) + (responsavel, responsavel),
    )
    pedidas = ex.um(
        "SELECT count(*) AS n FROM mapcartacomp.carga_trabalho c WHERE c.id = ANY(%s) OR c.id_lote_etapa = ANY(%s)",
        (list(ids or []), list(lote_etapas or [])),
    )["n"]
    if responsavel is not None and feitas["atribuidas"]:
        tocadas = ex.todos(
            "SELECT DISTINCT c.id_lote_etapa AS id FROM mapcartacomp.carga_trabalho c "
            "WHERE (c.id = ANY(%s) OR c.id_lote_etapa = ANY(%s)) AND c.responsavel IS NOT NULL",
            (list(ids or []), list(lote_etapas or [])),
        )
        _iniciar(ex, [r["id"] for r in tocadas], "Iniciada ao distribuir as cargas")
    return {"atribuidas": feitas["atribuidas"], "ja_estavam": feitas["alvo"] - feitas["atribuidas"],
            "fora": pedidas - feitas["alvo"]}  # fmt: skip
