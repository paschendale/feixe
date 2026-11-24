"""Cargas de trabalho: leituras e escritas das rotas. Recebe um `Executor` (ver o pacote)."""

from __future__ import annotations

from typing import Dict, List, Optional

from . import ErroDados, Executor, novo_uuid

# Passagens abertas dos lotes (pendentes ou em andamento, no máximo uma por lote): é o que o supervisor está
# distribuindo agora. Uma folha sem etapa aberta (esperando o supervisor andar) fica de fora (D-105).
SQL_PASSAGENS_ATUAIS = (
    "SELECT le.id FROM mapcartacomp.lote l JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id "
    "WHERE le.situacao IN ('pendente', 'em_andamento')"
)


def responsaveis_atuais(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Quem tem carga nas passagens atuais dos lotes da UF, com o nome do SGBC e quantas cargas tem."""
    sql = (
        "SELECT c.responsavel AS conta, coalesce(u.nom_usuario::text, c.responsavel) AS nome, count(*) AS cargas "
        "FROM mapcartacomp.carga_trabalho c "
        "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = c.responsavel "
        f"WHERE c.responsavel IS NOT NULL AND c.id_lote_etapa IN ({SQL_PASSAGENS_ATUAIS}"
    )
    params: tuple = ()
    if uf:
        sql += " AND l.uf = %s) AND c.uf = %s"
        params = (uf, uf)
    else:
        sql += ")"
    sql += " GROUP BY c.responsavel, u.nom_usuario ORDER BY 2"
    return ex.todos(sql, params)


# --- Minhas cargas (B2) ----------------------------------------------------------------------------------------------
# "Minhas" = responsavel = current_user: a conta conectada é a do usuário, como na vw_carga_trabalho.

_CAMPOS = (
    "c.id, c.uuid::text AS uuid, c.id_lote_etapa, le.id_lote, "
    "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, t.nome AS tema, fe.nome AS etapa, "
    "at.nome AS atividade, c.geocodigo, c.concluido, c.concluido_em, le.situacao AS situacao_etapa, "
    "ST_XMin(c.geom) AS xmin, ST_YMin(c.geom) AS ymin, ST_XMax(c.geom) AS xmax, ST_YMax(c.geom) AS ymax"
)
_JUNCOES = (
    "FROM mapcartacomp.carga_trabalho c "
    "JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
    "JOIN mapcartacomp.lote l ON l.id = le.id_lote "
    "JOIN mapcartacomp.tema t ON t.id = l.id_tema "
    "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
    "JOIN mapcartacomp.atividade at ON at.id = c.id_atividade "
)
ABERTAS = ("pendente", "em_andamento")
JANELA_DESFAZER_HORAS = 24


def minhas(ex: Executor, id_lote_etapa: Optional[int] = None, concluido: Optional[bool] = None, limite: int = 1000):
    sql = f"SELECT {_CAMPOS} {_JUNCOES} WHERE c.responsavel = current_user"
    params: list = []
    if id_lote_etapa is not None:
        sql += " AND c.id_lote_etapa = %s"
        params.append(id_lote_etapa)
    if concluido is not None:
        sql += " AND c.concluido = %s"
        params.append(concluido)
    sql += " ORDER BY folha_revisao, c.concluido, c.concluido_em DESC, c.id LIMIT %s"
    params.append(limite)
    return ex.todos(sql, tuple(params))


def uma(ex: Executor, id_carga: int) -> Optional[Dict]:
    return ex.um(f"SELECT {_CAMPOS}, c.responsavel {_JUNCOES} WHERE c.id = %s", (id_carga,))


def resumo(ex: Executor) -> Dict:
    """Frase-resumo e progresso por passagem (D-72): o que concluí, desde quando, e o que falta em quais folhas.

    Entram as passagens abertas em que tenho carga e as encerradas em que ainda tenho carga pendente.
    """
    total = ex.um(
        "SELECT count(*) FILTER (WHERE concluido) AS concluidas, min(concluido_em) AS desde, "
        "count(*) FILTER (WHERE NOT concluido) AS pendentes "
        "FROM mapcartacomp.carga_trabalho WHERE responsavel = current_user"
    )
    passagens = ex.todos(
        "SELECT le.id AS id_lote_etapa, le.id_lote, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "t.nome AS tema, fe.nome AS etapa, le.situacao, count(*) AS total, "
        "count(*) FILTER (WHERE c.concluido) AS concluidas, max(c.concluido_em) AS ultima_conclusao "
        f"{_JUNCOES}WHERE c.responsavel = current_user "
        "GROUP BY le.id, le.id_lote, l.tipo, l.nome, le.revisao, t.nome, fe.nome, le.situacao "
        "HAVING le.situacao IN ('pendente', 'em_andamento') OR bool_or(NOT c.concluido) "
        "ORDER BY count(*) FILTER (WHERE NOT c.concluido) = 0, folha_revisao"
    )
    pendentes_abertas = [p for p in passagens if p["total"] > p["concluidas"]]
    return {
        "concluidas": total["concluidas"],
        "desde": total["desde"],
        "pendentes": sum(p["total"] - p["concluidas"] for p in pendentes_abertas),
        "folhas_pendentes": len(pendentes_abertas),
        "passagens": passagens,
    }


def progresso(ex: Executor, id_lote_etapa: int) -> Dict:
    """Minhas cargas concluídas / total numa passagem: o "35/93" da barra de status."""
    return ex.um(
        "SELECT le.id AS id_lote_etapa, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "count(c.id) AS total, count(c.id) FILTER (WHERE c.concluido) AS concluidas "
        "FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "LEFT JOIN mapcartacomp.carga_trabalho c ON c.id_lote_etapa = le.id AND c.responsavel = current_user "
        "WHERE le.id = %s GROUP BY le.id, l.tipo, l.nome, le.revisao",
        (id_lote_etapa,),
    )


def _minha_para_mudar(ex: Executor, id_carga: int) -> Dict:
    linha = ex.um(
        "SELECT c.id, c.id_lote_etapa, c.concluido, c.responsavel = current_user AS minha, le.situacao, "
        f"c.concluido_em > now() - interval '{JANELA_DESFAZER_HORAS} hours' AS recente "
        "FROM mapcartacomp.carga_trabalho c JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
        "WHERE c.id = %s FOR UPDATE OF c",
        (id_carga,),
    )
    if not linha:
        raise ErroDados("carga não encontrada", 404)
    if not linha["minha"]:
        raise ErroDados("esta carga não está atribuída a você", 403)
    if linha["situacao"] not in ABERTAS:
        raise ErroDados("a etapa desta folha já foi encerrada pelo supervisor")
    return linha


def concluir(ex: Executor, id_carga: int) -> Dict:
    """Conclui uma carga minha. Concluir de novo não faz nada (o clique duplo não vira erro). Se era a minha última
    pendente (em qualquer etapa aberta), a minha fila (B8) me passa a próxima folha, na mesma transação: volta em
    `fila`."""
    from . import filas

    linha = _minha_para_mudar(ex, id_carga)
    fila = None
    if not linha["concluido"]:
        ex.executar("UPDATE mapcartacomp.carga_trabalho SET concluido = true WHERE id = %s", (id_carga,))
        fila = filas.puxar(ex, ex.um("SELECT current_user AS u")["u"])
    return {"carga": uma(ex, id_carga), "progresso": progresso(ex, linha["id_lote_etapa"]), "fila": fila}


def desfazer(ex: Executor, id_carga: int) -> Dict:
    """Desfaz a conclusão de uma carga minha, até 24 horas depois de concluir."""
    linha = _minha_para_mudar(ex, id_carga)
    if not linha["concluido"]:
        raise ErroDados("esta carga não está concluída")
    if not linha["recente"]:
        raise ErroDados(f"só dá para desfazer até {JANELA_DESFAZER_HORAS} horas depois de concluir")
    ex.executar("UPDATE mapcartacomp.carga_trabalho SET concluido = false WHERE id = %s", (id_carga,))
    return {"carga": uma(ex, id_carga), "progresso": progresso(ex, linha["id_lote_etapa"])}


def proxima(
    ex: Executor,
    referencia: Optional[int] = None,
    excluir: Optional[List[int]] = None,
    id_lote: Optional[int] = None,
) -> Optional[Dict]:
    """Minha próxima carga pendente: a mais próxima da referência (a carga atual ou a última que concluí), de
    preferência na mesma passagem. Só em passagens abertas. `excluir`: cargas a deixar de fora (as puladas, que o
    plugin guarda só na memória, D-102); `id_lote`: só nesta folha. Nenhuma pendente: None."""
    return ex.um(
        "WITH r AS (SELECT id_lote_etapa, ST_Centroid(geom) AS g FROM mapcartacomp.carga_trabalho WHERE id = "
        "coalesce(%s, (SELECT id FROM mapcartacomp.carga_trabalho WHERE responsavel = current_user AND concluido "
        "ORDER BY concluido_em DESC NULLS LAST LIMIT 1))) "
        f"SELECT {_CAMPOS} {_JUNCOES}LEFT JOIN r ON true "
        "WHERE c.responsavel = current_user AND NOT c.concluido AND le.situacao IN ('pendente', 'em_andamento') "
        "AND c.id <> coalesce(%s, -1) AND c.id <> ALL(%s::int[]) AND (%s::int IS NULL OR le.id_lote = %s) "
        "ORDER BY (c.id_lote_etapa = r.id_lote_etapa) DESC NULLS LAST, ST_Distance(ST_Centroid(c.geom), r.g) "
        "NULLS LAST, folha_revisao, c.id LIMIT 1",
        (referencia, referencia, list(excluir or []), id_lote, id_lote),
    )


# --- Gerar cargas pela grade estatística (B4) ------------------------------------------------------------------------


def _passagem_para_gerar(ex: Executor, id_lote_etapa: int, uf: Optional[str]) -> Dict:
    p = ex.um(
        "SELECT le.id, le.situacao, le.uf, le.id_fluxo_etapa, l.tipo, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, fe.nome AS etapa, "
        "coalesce(l.geom, ST_Multi(a.geom)) AS geom FROM mapcartacomp.lote_etapa le "
        "JOIN mapcartacomp.lote l ON l.id = le.id_lote JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN mapcartctrl.t_articulacao_scn a ON a.id_articulacao_scn = l.id_articulacao_scn WHERE le.id = %s",
        (id_lote_etapa,),
    )
    if not p or (uf and p["uf"] != uf):
        raise ErroDados("passagem não encontrada", 404)
    if p["situacao"] not in ABERTAS:
        raise ErroDados(f"{p['folha_revisao']}: a etapa {p['etapa']} já foi encerrada")
    grade = ex.todos(
        "SELECT a.id, a.nome, a.grade_nivel FROM mapcartacomp.fluxo_etapa_atividade fea "
        "JOIN mapcartacomp.atividade a ON a.id = fea.id_atividade "
        "WHERE fea.id_fluxo_etapa = %s AND a.geracao = 'grade' AND a.ativo",
        (p["id_fluxo_etapa"],),
    )
    if len(grade) != 1 or not grade[0]["grade_nivel"]:
        raise ErroDados(
            f"{p['folha_revisao']}: a etapa {p['etapa']} precisa de exatamente uma atividade com cargas pela grade "
            f"estatística e nível definido (tem {len(grade)})"
        )
    p["atividade"] = grade[0]
    if ex.um(
        "SELECT 1 FROM mapcartacomp.carga_trabalho WHERE id_lote_etapa = %s AND id_atividade = %s LIMIT 1",
        (id_lote_etapa, grade[0]["id"]),
    ):
        raise ErroDados(f"{p['folha_revisao']}: esta etapa já tem cargas de {grade[0]['nome']}")
    return p


def gerar_pela_grade(ex: Executor, id_lote_etapa: int, previa: bool, uf: Optional[str] = None) -> Dict:
    """Cargas da passagem: células da grade estatística no nível da atividade, com centroide no lote, inteiras e com
    geocódigo (D-73). Prévia devolve as células (geocódigo e WKT) sem gravar; gravar cria as cargas disponíveis."""
    p = _passagem_para_gerar(ex, id_lote_etapa, uf)
    a = p["atividade"]
    celulas = ex.todos(
        "SELECT geocodigo, ST_AsText(geom) AS wkt FROM mapcartacomp.f_grade_celulas(%s, %s)",
        (p["geom"], a["grade_nivel"]),
    )
    if not celulas:
        raise ErroDados(f"{p['folha_revisao']}: nenhuma célula da grade tem o centroide dentro do lote")
    resumo = {
        "id_lote_etapa": id_lote_etapa,
        "folha_revisao": p["folha_revisao"],
        "etapa": p["etapa"],
        "atividade": a["nome"],
        "grade_nivel": a["grade_nivel"],
        "celulas": len(celulas),
    }
    if previa:
        return {**resumo, "gravadas": 0, "previa": celulas}
    geocodigos = [c["geocodigo"] for c in celulas]
    gravadas = ex.executar(
        "INSERT INTO mapcartacomp.carga_trabalho (uuid, id_lote_etapa, id_atividade, geocodigo, geom) "
        "SELECT u.id, %s, %s, c.geocodigo, c.geom FROM mapcartacomp.f_grade_celulas(%s, %s) c "
        "JOIN unnest(%s::text[], %s::uuid[]) AS u (geocodigo, id) ON u.geocodigo = c.geocodigo",
        (id_lote_etapa, a["id"], p["geom"], a["grade_nivel"], geocodigos, [novo_uuid() for _ in geocodigos]),
    )
    return {**resumo, "gravadas": gravadas}


def preparar(ex: Executor, uf: str, ids_lote_etapa: List[int]) -> Dict:
    """O que a passagem recém-aberta precisa sem decisão de ninguém (D-109): as cargas pela grade, se a etapa tem uma
    atividade pela grade; se a etapa não tem atividade que gere cargas (nenhuma, ou só de geração "nenhuma", como o
    envio à GCQ), não há o que distribuir e ela começa já. Etapa com atividade que não é pela grade (CQ por amostragem,
    fase D; geração manual), ou que já tem cargas, fica como está, com o motivo em `avisos`.

    Em lote, em poucas idas e voltas: uma leitura das passagens, uma da grade de todas, um INSERT das cargas e um das
    etapas iniciadas. Volta `geradas` (por passagem), `iniciadas` (sem atividade) e `avisos` (as que ficaram sem
    cargas, com o motivo)."""
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
        "EXISTS (SELECT 1 FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id) AS tem_cargas "
        "FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.lote l ON l.id = le.id_lote "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN mapcartctrl.t_articulacao_scn ar ON ar.id_articulacao_scn = l.id_articulacao_scn "
        "WHERE le.id = ANY(%s) ORDER BY folha_revisao",
        (list(ids_lote_etapa),),
    )
    gerar, iniciar, avisos = [], [], []
    for p in ps:
        if p["uf"] != uf or p["situacao"] not in ABERTAS or p["tem_cargas"]:
            continue
        if not p["atividades"]:
            if p["situacao"] == "pendente":
                iniciar.append(p)
        elif p["grade"] and len(p["grade"]) == 1:
            gerar.append(p)
        elif p["grade"]:
            avisos.append({**_ident(p), "aviso": f"a etapa {p['etapa']} tem mais de uma atividade pela grade"})
        elif p["fase"] == "cq":
            avisos.append({**_ident(p), "aviso": "as amostras do CQ saem do plano de amostragem (fase D)"})
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
    if iniciar:
        obs = "Iniciada ao abrir: a etapa não tem atividade, não há cargas a distribuir"
        _iniciar(ex, [p["id"] for p in iniciar], obs)
    return {"geradas": geradas, "iniciadas": [_ident(p) for p in iniciar], "avisos": avisos}


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


# --- Equipe e atribuição (B5) ----------------------------------------------------------------------------------------
# Atribuição é do supervisor e não é transição de etapa. Mas é ela que começa o trabalho: a etapa a iniciar que recebe
# a primeira carga com dono passa a em andamento (D-109), com a linha no histórico. Só cargas pendentes de passagens
# abertas mudam de mão; carga concluída fica com quem a fez.

PERFIS_EXECUTORES = ("O", "V", "S")  # APM, avaliador, supervisor (que também executa)


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
        "AND NOT coalesce(u.ind_contasuper, false) AND p.cd_perfil = ANY(%s)"
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
        raise ErroDados("escolha as cargas ou as folhas", 400)
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


def dividir(ex: Executor, uf: str, id_lote_etapa: int, pessoas: List[str], previa: bool = True) -> Dict:
    """Sugestão de balanceamento (B5): as cargas disponíveis da passagem divididas entre as pessoas em blocos contíguos
    (de norte a sul, de oeste a leste), o mais iguais possível. Com previa, só devolve quantas fica com cada uma."""
    if not pessoas:
        raise ErroDados("escolha pelo menos uma pessoa", 400)
    ids = [
        r["id"]
        for r in ex.todos(
            "SELECT c.id FROM mapcartacomp.carga_trabalho c JOIN mapcartacomp.lote_etapa le ON le.id = c.id_lote_etapa "
            "WHERE c.id_lote_etapa = %s AND c.uf = %s AND c.responsavel IS NULL AND NOT c.concluido "
            "AND le.situacao IN ('pendente', 'em_andamento') "
            "ORDER BY round(ST_Y(ST_Centroid(c.geom))::numeric, 3) DESC, ST_X(ST_Centroid(c.geom)), c.id",
            (id_lote_etapa, uf),
        )
    ]
    base, sobra = divmod(len(ids), len(pessoas))
    plano, i = [], 0
    for k, conta in enumerate(pessoas):
        n = base + (1 if k < sobra else 0)
        plano.append({"conta": conta, "cargas": n, "ids": ids[i : i + n]})
        i += n
    if not previa:
        for p in plano:
            if p["ids"]:
                atribuir(ex, uf, p["conta"], ids=p["ids"], so_disponiveis=True)
    return {"disponiveis": len(ids), "plano": [{"conta": p["conta"], "cargas": p["cargas"]} for p in plano]}
