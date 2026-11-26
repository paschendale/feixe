"""Fluxos da GGC e o andar da folha pelas etapas (B6). Nada avança sozinho: toda mudança é ação do supervisor, com
observação, registrada em lote_etapa_hist. O plugin só sugere a próxima etapa.

Modelo de passagem: cada lote tem no máximo uma passagem aberta (pendente ou em andamento). Avançar, repetir uma
etapa repetível ou voltar a uma etapa anterior é o mesmo gesto: abrir uma nova passagem numa etapa do fluxo.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..cq import amostragem as am
from . import ErroDados, Executor, novo_uuid
from . import cq as dcq

ABERTAS = ("pendente", "em_andamento")
CAMPOS_ETAPA = (
    "ordem", "fase", "nome", "obrigatoria", "repetivel", "conta_revisao", "fracao_critica", "nivel_inspecao", "lqa",
)  # fmt: skip
CAMPOS_CQ = ("fracao_critica", "nivel_inspecao", "lqa")  # padrão dos planos de amostragem, só na etapa de CQ (D-135)

# Fluxo modelo da CCAR (D-65): o caminho do DF. Fica no código, não no banco, porque um fluxo no banco é de uma UF.
# As atividades de cada etapa são escolhidas no catálogo pelo projeto, tema e fase; no CQ, todas as ativas do tema, com
# o padrão dos planos no nível II e LQA 4% (a fração crítica fica a de cada elemento, 4% na CCAR, D-75): abrir o CQ já
# sorteia as amostras (D-136), e a GGC troca o padrão no editor.
MODELO_CCAR = [
    {"fase": "aquisicao", "nome": "Aquisição", "obrigatoria": True, "repetivel": False, "conta_revisao": True},
    {"fase": "revisao", "nome": "Revisão por outra pessoa", "obrigatoria": False, "repetivel": True,
     "conta_revisao": True},
    {"fase": "cq", "nome": "Controle de qualidade", "obrigatoria": False, "repetivel": True, "conta_revisao": False,
     "nivel_inspecao": "II", "lqa": 4},
    {"fase": "correcao_inspecao", "nome": "Correção de inspeção", "obrigatoria": False, "repetivel": True,
     "conta_revisao": False},
    {"fase": "correcao_topologica", "nome": "Correção topológica", "obrigatoria": True, "repetivel": True,
     "conta_revisao": False},
    {"fase": "envio_gcq", "nome": "Envio à GCQ", "obrigatoria": True, "repetivel": True, "conta_revisao": False},
]  # fmt: skip


# Última passagem da folha `l` (a mais recente, concluída, pulada ou aberta). É dela que se conta "a seguinte" (D-107):
# a etapa atual (`id_lote_etapa_atual`) ignora as puladas porque dirige o status nacional, e contar a partir dela
# devolveria a etapa que o supervisor acabou de pular. Uma passagem nova só abre sem outra aberta, então a ordem dos
# ids é a ordem das decisões.
_ULTIMA = "(SELECT max(x.id) FROM mapcartacomp.lote_etapa x WHERE x.id_lote = l.id)"


# --- Fluxos ----------------------------------------------------------------------------------------------------------


def listar(ex: Executor, uf: Optional[str]) -> List[Dict]:
    """Fluxos com etapas e atividades. Com UF, só os dela; sem, todos (para copiar de outra unidade)."""
    fluxos = ex.todos(
        "SELECT f.id, f.nome, f.uf, f.ativo, f.cod_projeto, p.nom_projeto AS projeto, f.id_tema, t.nome AS tema, "
        "(SELECT count(*) FROM mapcartacomp.lote l WHERE l.id_fluxo = f.id) AS lotes "
        "FROM mapcartacomp.fluxo f JOIN mapcartacomp.tema t ON t.id = f.id_tema "
        "JOIN mapcartctrl.t_projeto p ON p.cod_projeto = f.cod_projeto"
        + (" WHERE f.uf = %s" if uf else "")
        + " ORDER BY f.uf, p.nom_projeto, t.nome, f.nome",
        (uf,) if uf else (),
    )
    if not fluxos:
        return []
    etapas = ex.todos(
        "SELECT fe.id, fe.id_fluxo, fe.ordem, fe.fase, fa.nome AS fase_nome, fe.nome, fe.obrigatoria, fe.repetivel, "
        "fe.conta_revisao, fe.fracao_critica::float8 AS fracao_critica, fe.nivel_inspecao, fe.lqa::float8 AS lqa, "
        "(SELECT count(*) FROM mapcartacomp.lote_etapa le WHERE le.id_fluxo_etapa = fe.id) AS passagens, "
        "coalesce((SELECT json_agg(json_build_object('id', a.id, 'nome', a.nome, 'geracao', a.geracao) "
        "ORDER BY a.nome) "
        "FROM mapcartacomp.fluxo_etapa_atividade fea JOIN mapcartacomp.atividade a ON a.id = fea.id_atividade "
        "WHERE fea.id_fluxo_etapa = fe.id), '[]') AS atividades "
        "FROM mapcartacomp.fluxo_etapa fe JOIN mapcartacomp.fase fa ON fa.codigo = fe.fase "
        "WHERE fe.id_fluxo = ANY(%s) ORDER BY fe.ordem",
        ([f["id"] for f in fluxos],),
    )
    for f in fluxos:
        f["etapas"] = [e for e in etapas if e["id_fluxo"] == f["id"]]
    return fluxos


def _um(ex: Executor, id_fluxo: int) -> Dict:
    f = ex.um("SELECT id, uf, cod_projeto, id_tema, nome, ativo FROM mapcartacomp.fluxo WHERE id = %s", (id_fluxo,))
    if not f:
        raise ErroDados("fluxo não encontrado", 404)
    return f


def _validar_etapas(ex: Executor, cod_projeto: int, id_tema: int, etapas: List[Dict]) -> None:
    if not etapas:
        raise ErroDados("o fluxo precisa de pelo menos uma etapa", 400)
    fases = {r["codigo"] for r in ex.todos("SELECT codigo FROM mapcartacomp.fase")}
    for i, e in enumerate(etapas, start=1):
        if not (e.get("nome") or "").strip():
            raise ErroDados(f"etapa {i}: dê um nome", 400)
        if e.get("fase") not in fases:
            raise ErroDados(f"etapa {i}: fase desconhecida", 400)
        fc = e.get("fracao_critica")
        if fc is not None and (e["fase"] != "cq" or not 0 < float(fc) < 100):
            raise ErroDados(f"etapa {i}: fração crítica só na etapa de CQ, entre 0 e 100%", 400)
        _padrao_cq(e, i)
        ids = e.get("atividades") or []
        if ids:
            ok = ex.um(
                "SELECT count(*) AS n FROM mapcartacomp.atividade WHERE id = ANY(%s) AND cod_projeto = %s "
                "AND id_tema = %s AND fase = %s",
                (list(ids), cod_projeto, id_tema, e["fase"]),
            )["n"]
            if ok != len(set(ids)):
                raise ErroDados(f"etapa {i} ({e['nome']}): atividade de outro projeto, tema ou fase", 400)


def _padrao_cq(e: Dict, i: int) -> None:
    """Nível de inspeção e LQA padrão da etapa de CQ, normalizados ("2" vira "II", "2,5" vira 2.5) e conferidos nos
    quadros do manual; fora do CQ não há padrão. Vazio = o supervisor escolhe ao criar o plano."""
    nivel, lqa = e.get("nivel_inspecao"), e.get("lqa")
    if nivel in ("", None):
        nivel = None
    if lqa in ("", None):
        lqa = None
    if e["fase"] != "cq":
        if nivel is not None or lqa is not None:
            raise ErroDados(f"etapa {i}: nível de inspeção e LQA só na etapa de CQ", 400)
        return
    try:
        e["nivel_inspecao"] = None if nivel is None else am.normalizar_nivel(nivel)
        e["lqa"] = None if lqa is None else am.normalizar_lqa(lqa)
    except am.ErroAmostragem as erro:
        raise ErroDados(f"etapa {i} ({e['nome']}): {erro}", 400) from None


def _gravar_etapas(ex: Executor, id_fluxo: int, etapas: List[Dict]) -> None:
    """Etapas com id são atualizadas, sem id são criadas, e as que sumiram são apagadas (só se não têm passagem).
    A ordem é a da lista; a unicidade de (fluxo, ordem) é adiada para permitir reordenar."""
    ex.executar("SET CONSTRAINTS ALL DEFERRED")
    atuais = {
        r["id"]: r
        for r in ex.todos(
            "SELECT fe.id, fe.nome, (SELECT count(*) FROM mapcartacomp.lote_etapa le WHERE le.id_fluxo_etapa = fe.id) "
            "AS passagens FROM mapcartacomp.fluxo_etapa fe WHERE fe.id_fluxo = %s",
            (id_fluxo,),
        )
    }
    ficam = {e["id"] for e in etapas if e.get("id")}
    if ficam - set(atuais):
        raise ErroDados("etapa de outro fluxo", 400)
    for id_etapa, r in atuais.items():
        if id_etapa not in ficam:
            if r["passagens"]:
                raise ErroDados(f"a etapa {r['nome']} já tem passagens de folhas e não pode sair do fluxo")
            ex.executar("DELETE FROM mapcartacomp.fluxo_etapa WHERE id = %s", (id_etapa,))
    for ordem, e in enumerate(etapas, start=1):
        valores = (
            ordem, e["fase"], e["nome"].strip(), e.get("obrigatoria", True), e.get("repetivel", False),
            e.get("conta_revisao", False), *(e.get(c) if e["fase"] == "cq" else None for c in CAMPOS_CQ),
        )  # fmt: skip
        if e.get("id"):
            if atuais[e["id"]]["passagens"]:
                fase = ex.um("SELECT fase FROM mapcartacomp.fluxo_etapa WHERE id = %s", (e["id"],))["fase"]
                if fase != e["fase"]:
                    raise ErroDados(f"a etapa {e['nome']} já tem passagens: a fase não muda")
            ex.executar(
                f"UPDATE mapcartacomp.fluxo_etapa SET {', '.join(f'{c} = %s' for c in CAMPOS_ETAPA)} WHERE id = %s",
                valores + (e["id"],),
            )
            id_etapa = e["id"]
        else:
            id_etapa = ex.um(
                f"INSERT INTO mapcartacomp.fluxo_etapa (id_fluxo, {', '.join(CAMPOS_ETAPA)}) "
                f"VALUES (%s, {', '.join(['%s'] * len(CAMPOS_ETAPA))}) RETURNING id",
                (id_fluxo,) + valores,
            )["id"]
        ids = sorted(set(e.get("atividades") or []))
        ex.executar(
            "DELETE FROM mapcartacomp.fluxo_etapa_atividade WHERE id_fluxo_etapa = %s AND NOT id_atividade = ANY(%s)",
            (id_etapa, ids),
        )
        for a in ids:
            ex.executar(
                "INSERT INTO mapcartacomp.fluxo_etapa_atividade (id_fluxo_etapa, id_atividade) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (id_etapa, a),
            )
    ex.executar("SET CONSTRAINTS ALL IMMEDIATE")


def _nome_livre(ex: Executor, uf, cod_projeto, id_tema, nome, exceto=None) -> None:
    if ex.um(
        "SELECT 1 FROM mapcartacomp.fluxo WHERE uf = %s AND cod_projeto = %s AND id_tema = %s AND nome = %s "
        "AND id <> coalesce(%s, -1)",
        (uf, cod_projeto, id_tema, nome, exceto),
    ):
        raise ErroDados(f"já existe o fluxo {nome} neste projeto e tema")


def criar(ex: Executor, uf: str, cod_projeto: int, id_tema: int, nome: str, etapas: List[Dict]) -> Dict:
    nome = (nome or "").strip()
    if not nome:
        raise ErroDados("dê um nome ao fluxo", 400)
    _validar_etapas(ex, cod_projeto, id_tema, etapas)
    _nome_livre(ex, uf, cod_projeto, id_tema, nome)
    id_fluxo = ex.um(
        "INSERT INTO mapcartacomp.fluxo (cod_projeto, id_tema, uf, nome) VALUES (%s, %s, %s, %s) RETURNING id",
        (cod_projeto, id_tema, uf, nome),
    )["id"]
    _gravar_etapas(ex, id_fluxo, [{k: v for k, v in e.items() if k != "id"} for e in etapas])
    return next(f for f in listar(ex, uf) if f["id"] == id_fluxo)


def alterar(ex: Executor, uf: str, id_fluxo: int, nome: Optional[str], ativo: Optional[bool], etapas=None) -> Dict:
    f = _um(ex, id_fluxo)
    if f["uf"] != uf:
        raise ErroDados("fluxo de outra unidade: copie-o para a sua antes de mudar", 403)
    nome = (nome if nome is not None else f["nome"]).strip()
    _nome_livre(ex, uf, f["cod_projeto"], f["id_tema"], nome, id_fluxo)
    if etapas is not None:
        _validar_etapas(ex, f["cod_projeto"], f["id_tema"], etapas)
        _gravar_etapas(ex, id_fluxo, etapas)
    ex.executar(
        "UPDATE mapcartacomp.fluxo SET nome = %s, ativo = %s WHERE id = %s",
        (nome, f["ativo"] if ativo is None else ativo, id_fluxo),
    )
    return next(x for x in listar(ex, uf) if x["id"] == id_fluxo)


def _padrao_copiavel(e: Dict) -> Dict:
    """Padrão de CQ de uma etapa copiada de outra unidade: o que se normaliza fica ("2" vira "II"); nível ou LQA fora
    dos quadros do manual (o banco aceita texto aberto) sai, e a etapa cai em "Criar os planos de CQ" na gaveta, em
    vez de a cópia falhar."""
    for campo, normalizar in (("nivel_inspecao", am.normalizar_nivel), ("lqa", am.normalizar_lqa)):
        if e.get(campo) is not None:
            try:
                e[campo] = normalizar(e[campo])
            except am.ErroAmostragem:
                e[campo] = None
    return e


def copiar(ex: Executor, uf: str, id_origem: int, nome: str) -> Dict:
    """Copia o fluxo de qualquer unidade para a minha, com as mesmas etapas e atividades."""
    origem = next((f for f in listar(ex, None) if f["id"] == id_origem), None)
    if not origem:
        raise ErroDados("fluxo não encontrado", 404)
    etapas = [
        _padrao_copiavel({**{k: e[k] for k in CAMPOS_ETAPA}, "atividades": [a["id"] for a in e["atividades"]]})
        for e in origem["etapas"]
    ]
    return criar(ex, uf, origem["cod_projeto"], origem["id_tema"], nome, etapas)


def do_modelo(ex: Executor, uf: str, cod_projeto: int, id_tema: int, nome: str) -> Dict:
    """Fluxo novo a partir do modelo da CCAR, com as atividades ativas do catálogo para o projeto, tema e fase."""
    ativs = ex.todos(
        "SELECT id, fase FROM mapcartacomp.atividade WHERE cod_projeto = %s AND id_tema = %s AND ativo",
        (cod_projeto, id_tema),
    )
    etapas = []
    for e in MODELO_CCAR:
        # A revisão fica sem atividade: no catálogo, as de fase revisão são revisões pontuais de cada GGC, e quem
        # escolhe é o supervisor ao ajustar o fluxo.
        do_tipo = [] if e["fase"] == "revisao" else [a["id"] for a in ativs if a["fase"] == e["fase"]]
        etapas.append({**e, "atividades": do_tipo})
    return criar(ex, uf, cod_projeto, id_tema, nome, etapas)


# --- Andar com a folha -----------------------------------------------------------------------------------------------


def _hist(ex: Executor, id_lote_etapa: int, acao: str, observacao: str) -> None:
    ex.executar(
        "INSERT INTO mapcartacomp.lote_etapa_hist (uuid, id_lote_etapa, acao, observacao) VALUES (%s, %s, %s, %s)",
        (novo_uuid(), id_lote_etapa, acao, observacao),
    )


def _obs(observacao: Optional[str]) -> str:
    o = (observacao or "").strip()
    if not o:
        raise ErroDados("escreva uma observação: toda mudança de etapa fica no histórico da folha", 400)
    return o


def _passagem(ex: Executor, id_lote_etapa: int, uf: str) -> Dict:
    p = ex.um(
        "SELECT le.id, le.id_lote, le.uf, le.situacao, le.instancia, fe.fase, fe.nome AS etapa, fe.obrigatoria, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "(SELECT max(x.id) FROM mapcartacomp.lote_etapa x WHERE x.id_lote = le.id_lote AND x.situacao <> 'pulada') "
        "AS ultima FROM mapcartacomp.lote_etapa le JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "JOIN mapcartacomp.lote l ON l.id = le.id_lote WHERE le.id = %s FOR UPDATE OF le",
        (id_lote_etapa,),
    )
    if not p or p["uf"] != uf:
        raise ErroDados("passagem não encontrada na sua unidade", 404)
    return p


def _outra_aberta(ex: Executor, id_lote: int, exceto: int) -> Optional[Dict]:
    return ex.um(
        "SELECT le.id, fe.nome AS etapa, le.situacao FROM mapcartacomp.lote_etapa le "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "WHERE le.id_lote = %s AND le.id <> %s AND le.situacao IN ('pendente', 'em_andamento')",
        (id_lote, exceto),
    )


def acao(ex: Executor, uf: str, id_lote_etapa: int, qual: str, observacao: str, resultado: Optional[str] = None):
    """iniciar (pendente), concluir (em andamento), pular (pendente e não obrigatória), reabrir (a última concluída,
    se não há outra aberta) e gcq (no envio à GCQ em andamento: aprovada ou devolvida, e a passagem conclui)."""
    obs = _obs(observacao)
    p = _passagem(ex, id_lote_etapa, uf)
    s, nome = p["situacao"], f"{p['folha_revisao']}, {p['etapa']}"
    if qual == "iniciar":
        if s != "pendente":
            raise ErroDados(f"{nome}: só se inicia etapa a iniciar")
        ex.executar(
            "UPDATE mapcartacomp.lote_etapa SET situacao = 'em_andamento', iniciada_em = now() WHERE id = %s",
            (p["id"],),
        )
    elif qual == "concluir":
        if s != "em_andamento":
            raise ErroDados(f"{nome}: só se conclui etapa em andamento")
        ex.executar(
            "UPDATE mapcartacomp.lote_etapa SET situacao = 'concluida', concluida_em = now(), "
            "concluida_por = current_user WHERE id = %s",
            (p["id"],),
        )
    elif qual == "pular":
        if s != "pendente":
            raise ErroDados(f"{nome}: só se pula etapa a iniciar")
        if p["obrigatoria"]:
            raise ErroDados(f"{nome}: etapa obrigatória do fluxo não pode ser pulada")
        ex.executar("UPDATE mapcartacomp.lote_etapa SET situacao = 'pulada' WHERE id = %s", (p["id"],))
    elif qual == "reabrir":
        if s != "concluida" or p["ultima"] != p["id"]:
            raise ErroDados(f"{nome}: só se reabre a última etapa concluída")
        aberta = _outra_aberta(ex, p["id_lote"], p["id"])
        if aberta:
            raise ErroDados(f"a folha já tem a etapa {aberta['etapa']} aberta")
        ex.executar(
            "UPDATE mapcartacomp.lote_etapa SET situacao = 'em_andamento', concluida_em = NULL, concluida_por = NULL, "
            "resultado = NULL WHERE id = %s",
            (p["id"],),
        )
    elif qual == "gcq":
        if p["fase"] != "envio_gcq" or s != "em_andamento":
            raise ErroDados(f"{nome}: o resultado da GCQ se registra no envio à GCQ em andamento")
        if resultado not in ("aprovada", "devolvida"):
            raise ErroDados("resultado da GCQ: aprovada ou devolvida", 400)
        ex.executar(
            "UPDATE mapcartacomp.lote_etapa SET resultado = %s, situacao = 'concluida', concluida_em = now(), "
            "concluida_por = current_user WHERE id = %s",
            (resultado, p["id"]),
        )
        qual = f"gcq_{resultado}"
    else:
        raise ErroDados("ação desconhecida", 400)
    _hist(ex, p["id"], qual, obs)
    return estado(ex, p["id_lote"])


def nova_passagem(
    ex: Executor, uf: str, id_lote: int, id_fluxo_etapa: int, observacao: str, expor_ocorrencias: bool = False
) -> Dict:
    """Abre uma passagem numa etapa do fluxo do lote: avançar, repetir (etapa repetível) ou voltar. A revisão é
    derivada (conta_revisao). expor_ocorrencias: o supervisor inclui as correções a fazer (D-66); padrão às cegas."""
    obs = _obs(observacao)
    lote = ex.um("SELECT id, uf, id_fluxo FROM mapcartacomp.lote WHERE id = %s FOR UPDATE", (id_lote,))
    if not lote or lote["uf"] != uf:
        raise ErroDados("lote não encontrado na sua unidade", 404)
    etapa = ex.um(
        "SELECT id, nome, repetivel FROM mapcartacomp.fluxo_etapa WHERE id = %s AND id_fluxo = %s",
        (id_fluxo_etapa, lote["id_fluxo"]),
    )
    if not etapa:
        raise ErroDados("etapa fora do fluxo desta folha", 400)
    aberta = _outra_aberta(ex, id_lote, -1)
    if aberta:
        raise ErroDados(f"a folha já tem a etapa {aberta['etapa']} aberta: conclua ou pule antes")
    feitas = ex.um(
        "SELECT count(*) AS n, coalesce(max(instancia), 0) AS ultima FROM mapcartacomp.lote_etapa "
        "WHERE id_lote = %s AND id_fluxo_etapa = %s",
        (id_lote, id_fluxo_etapa),
    )
    nao_puladas = ex.um(
        "SELECT count(*) AS n FROM mapcartacomp.lote_etapa WHERE id_lote = %s AND id_fluxo_etapa = %s "
        "AND situacao <> 'pulada'",
        (id_lote, id_fluxo_etapa),
    )["n"]
    if nao_puladas and not etapa["repetivel"]:
        raise ErroDados(f"a etapa {etapa['nome']} não se repete neste fluxo")
    id_le = ex.um(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, instancia, expor_ocorrencias) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (novo_uuid(), id_lote, id_fluxo_etapa, feitas["ultima"] + 1, bool(expor_ocorrencias)),
    )["id"]
    _hist(ex, id_le, "repetir" if feitas["n"] else "abrir", obs)
    return {**estado(ex, id_lote), "id_lote_etapa": id_le}


def abrir_proximas(ex: Executor, uf: str, ids: List[int], observacao: str) -> Dict:
    """Abre a etapa sugerida (a seguinte na ordem do fluxo) em várias folhas: as mesmas regras de `nova_passagem`,
    em quatro idas e voltas ao banco, qualquer que seja o número de folhas (D-104). As recusadas voltam em `erros`
    com o motivo; as outras abrem."""
    obs = _obs(observacao)
    linhas = ex.todos(
        "SELECT l.id, l.uf, le.situacao, n.id AS id_etapa, n.nome AS etapa, n.repetivel, "
        "(SELECT fe2.nome FROM mapcartacomp.lote_etapa x "
        " JOIN mapcartacomp.fluxo_etapa fe2 ON fe2.id = x.id_fluxo_etapa "
        " WHERE x.id_lote = l.id AND x.situacao IN ('pendente', 'em_andamento') LIMIT 1) AS aberta, "
        "(SELECT count(*) FROM mapcartacomp.lote_etapa x WHERE x.id_lote = l.id "
        " AND x.id_fluxo_etapa = n.id) AS feitas, "
        "(SELECT count(*) FROM mapcartacomp.lote_etapa x WHERE x.id_lote = l.id AND x.id_fluxo_etapa = n.id "
        " AND x.situacao <> 'pulada') AS nao_puladas, "
        "(SELECT coalesce(max(x.instancia), 0) FROM mapcartacomp.lote_etapa x WHERE x.id_lote = l.id "
        " AND x.id_fluxo_etapa = n.id) AS ultima "
        "FROM mapcartacomp.lote l "
        f"LEFT JOIN mapcartacomp.lote_etapa le ON le.id = {_ULTIMA} "
        "LEFT JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN LATERAL (SELECT x.id, x.nome, x.repetivel FROM mapcartacomp.fluxo_etapa x "
        " WHERE x.id_fluxo = l.id_fluxo AND x.ordem > coalesce(fe.ordem, 0) ORDER BY x.ordem LIMIT 1) n ON true "
        "WHERE l.id = ANY(%s) FOR UPDATE OF l",
        (list(ids),),
    )
    por_id = {r["id"]: r for r in linhas}
    erros, validas = [], []
    for i in ids:
        r = por_id.get(i)
        if not r or r["uf"] != uf:
            erros.append({"id_lote": i, "erro": "lote não encontrado na sua unidade"})
        elif r["aberta"]:
            erros.append({"id_lote": i, "erro": f"a folha já tem a etapa {r['aberta']} aberta"})
        elif r["id_etapa"] is None:
            erros.append({"id_lote": i, "erro": "sem próxima etapa no fluxo"})
        elif r["nao_puladas"] and not r["repetivel"]:
            erros.append({"id_lote": i, "erro": f"a etapa {r['etapa']} não se repete neste fluxo"})
        else:
            validas.append(r)
    if not validas:
        return {"abertas": [], "erros": erros}
    novas = ex.todos(
        "INSERT INTO mapcartacomp.lote_etapa (uuid, id_lote, id_fluxo_etapa, instancia, expor_ocorrencias) "
        "SELECT u::uuid, l, e, i, false FROM unnest(%s::text[], %s::int[], %s::int[], %s::int[]) AS t(u, l, e, i) "
        "RETURNING id, id_lote",
        (
            [novo_uuid() for _ in validas],
            [r["id"] for r in validas],
            [r["id_etapa"] for r in validas],
            [r["ultima"] + 1 for r in validas],
        ),
    )
    acao = {r["id"]: "repetir" if r["feitas"] else "abrir" for r in validas}
    ex.executar(
        "INSERT INTO mapcartacomp.lote_etapa_hist (uuid, id_lote_etapa, acao, observacao) "
        "SELECT u::uuid, le, a, %s FROM unnest(%s::text[], %s::int[], %s::text[]) AS t(u, le, a)",
        (obs, [novo_uuid() for _ in novas], [n["id"] for n in novas], [acao[n["id_lote"]] for n in novas]),
    )
    etapa = {r["id"]: r["etapa"] for r in validas}
    return {
        "abertas": [{"id_lote": n["id_lote"], "id_lote_etapa": n["id"], "etapa": etapa[n["id_lote"]]} for n in novas],
        "erros": erros,
    }


def avancar(ex: Executor, uf: str, ids: List[int], observacao: Optional[str], previa: bool) -> Dict:
    """Próxima etapa em várias folhas (D-109): a folha com a etapa em andamento conclui essa etapa e abre a seguinte; a
    que já terminou a etapa só abre a seguinte. Na prévia, volta por folha o que vai acontecer (ou por que não), para o
    supervisor confirmar; sem prévia, faz, em poucas idas e voltas, e as recusadas voltam em `erros`.

    Recusa: etapa a iniciar (ainda não começou: distribua as cargas ou pule pela gaveta), envio à GCQ em andamento (o
    resultado da GCQ se registra na gaveta) e fim do fluxo."""
    linhas = ex.todos(
        "SELECT l.id AS id_lote, l.uf, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS folha_revisao, "
        "t.nome AS tema, le.id AS id_lote_etapa, le.situacao, fe.nome AS etapa, fe.fase, "
        "(SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id) AS cargas, "
        "(SELECT count(*) FROM mapcartacomp.carga_trabalho c WHERE c.id_lote_etapa = le.id AND NOT c.concluido) "
        "AS pendentes, n.nome AS proxima, n.repetivel, "
        "(SELECT count(*) FROM mapcartacomp.lote_etapa x WHERE x.id_lote = l.id AND x.id_fluxo_etapa = n.id "
        " AND x.situacao <> 'pulada') AS nao_puladas "
        "FROM mapcartacomp.lote l JOIN mapcartacomp.tema t ON t.id = l.id_tema "
        "LEFT JOIN mapcartacomp.lote_etapa le ON le.id = coalesce((SELECT x.id FROM mapcartacomp.lote_etapa x "
        f"WHERE x.id_lote = l.id AND x.situacao IN ('pendente', 'em_andamento') LIMIT 1), {_ULTIMA}) "
        "LEFT JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN LATERAL (SELECT x.id, x.nome, x.repetivel FROM mapcartacomp.fluxo_etapa x "
        " WHERE x.id_fluxo = l.id_fluxo AND x.ordem > coalesce(fe.ordem, 0) ORDER BY x.ordem LIMIT 1) n ON true "
        "WHERE l.id = ANY(%s) ORDER BY t.nome, folha_revisao" + ("" if previa else " FOR UPDATE OF l"),
        (list(ids),),
    )
    itens = []
    for r in linhas:
        erro = None
        if r["uf"] != uf:
            erro = "folha de outra unidade"
        elif r["situacao"] == "pendente":
            erro = f"{r['etapa']} ainda não começou: distribua as cargas, ou pule a etapa pela gaveta"
        elif r["situacao"] == "em_andamento" and r["fase"] == "envio_gcq":
            erro = "o resultado da GCQ se registra na gaveta da folha"
        elif r["situacao"] == "em_andamento" and r["fase"] == "cq":
            # O CQ termina pela decisão sobre o resultado (D4), que fica registrada: aprovar ou nova revisão.
            erro = (
                "o CQ termina pela decisão sobre o resultado: Aprovar ou Nova revisão, em Esperando você ou na gaveta"
            )
        elif r["proxima"] is None:
            erro = "é a última etapa do fluxo"
        elif r["nao_puladas"] and not r["repetivel"]:
            erro = f"a etapa {r['proxima']} não se repete neste fluxo"
        itens.append({
            "id_lote": r["id_lote"], "folha_revisao": r["folha_revisao"], "tema": r["tema"], "etapa": r["etapa"],
            "concluir": r["situacao"] == "em_andamento", "cargas": r["cargas"], "pendentes": r["pendentes"],
            "proxima": r["proxima"], "erro": erro,
        })  # fmt: skip
    if previa:
        return {"itens": itens}
    obs = _obs(observacao)
    validos = [i for i in itens if not i["erro"]]
    erros = [{"id_lote": i["id_lote"], "erro": i["erro"]} for i in itens if i["erro"]]
    concluir = [r["id_lote_etapa"] for r, i in zip(linhas, itens) if not i["erro"] and i["concluir"]]
    if concluir:
        ex.executar(
            "UPDATE mapcartacomp.lote_etapa SET situacao = 'concluida', concluida_em = now(), "
            "concluida_por = current_user WHERE id = ANY(%s) AND situacao = 'em_andamento'",
            (concluir,),
        )
        ex.executar(
            "INSERT INTO mapcartacomp.lote_etapa_hist (uuid, id_lote_etapa, acao, observacao) "
            "SELECT u::uuid, le, 'concluir', %s FROM unnest(%s::text[], %s::int[]) AS t(u, le)",
            (obs, [novo_uuid() for _ in concluir], concluir),
        )
    if not validos:
        return {"abertas": [], "erros": erros}
    r = abrir_proximas(ex, uf, [i["id_lote"] for i in validos], obs)
    return {"abertas": r["abertas"], "erros": erros + r["erros"]}


# --- Decisão sobre o resultado do CQ (D4) ----------------------------------------------------------------------------

DECISOES_CQ = ("aprovar", "nova_revisao")


def _alvos_cq(ex: Executor, ids: List[int], travar: bool) -> List[Dict]:
    """A passagem de CQ de cada folha (a aberta ou, sem nenhuma aberta, a última), a etapa seguinte do fluxo e a etapa
    de revisão da nova revisão: a mais recente antes do CQ que conta revisão e se repete."""
    return ex.todos(
        "SELECT l.id AS id_lote, l.uf, l.tipo, l.nome, mapcartacomp.f_rotulo(l.tipo, l.nome, le.revisao) AS "
        "folha_revisao, t.nome AS tema, le.id AS id_lote_etapa, le.situacao, le.resultado, le.revisao, fe.fase, "
        "fe.nome AS etapa, n.id AS id_proxima, n.nome AS proxima, n.repetivel AS proxima_repetivel, "
        "(SELECT count(*) FROM mapcartacomp.lote_etapa x WHERE x.id_lote = l.id AND x.id_fluxo_etapa = n.id "
        " AND x.situacao <> 'pulada') AS proxima_feitas, rv.id AS id_revisao, rv.nome AS revisao_etapa, "
        "mapcartacomp.f_rotulo(l.tipo, l.nome, (1 + (SELECT count(*) FROM mapcartacomp.lote_etapa x "
        " JOIN mapcartacomp.fluxo_etapa fx ON fx.id = x.id_fluxo_etapa WHERE x.id_lote = l.id AND fx.conta_revisao "
        " AND x.situacao <> 'pulada'))::int) AS nova_folha, "
        # Quem fez a revisão avaliada (a passagem que conta revisão na mesma revisão do CQ): a nova revisão vai para
        # outra pessoa (a sugestão do Distribuir já evita quem trabalhou na folha, D-109).
        "(SELECT array_agg(DISTINCT coalesce(u.nom_usuario::text, c.responsavel)) FROM mapcartacomp.lote_etapa x "
        " JOIN mapcartacomp.fluxo_etapa fx ON fx.id = x.id_fluxo_etapa AND fx.conta_revisao "
        " JOIN mapcartacomp.carga_trabalho c ON c.id_lote_etapa = x.id AND c.responsavel IS NOT NULL "
        " LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = c.responsavel "
        " WHERE x.id_lote = l.id AND x.revisao = le.revisao AND x.id <> le.id AND x.situacao <> 'pulada') AS autores "
        "FROM mapcartacomp.lote l JOIN mapcartacomp.tema t ON t.id = l.id_tema "
        "LEFT JOIN mapcartacomp.lote_etapa le ON le.id = coalesce((SELECT x.id FROM mapcartacomp.lote_etapa x "
        f"WHERE x.id_lote = l.id AND x.situacao IN ('pendente', 'em_andamento') LIMIT 1), {_ULTIMA}) "
        "LEFT JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN LATERAL (SELECT x.id, x.nome, x.repetivel FROM mapcartacomp.fluxo_etapa x "
        " WHERE x.id_fluxo = l.id_fluxo AND x.ordem > fe.ordem ORDER BY x.ordem LIMIT 1) n ON true "
        "LEFT JOIN LATERAL (SELECT x.id, x.nome FROM mapcartacomp.fluxo_etapa x WHERE x.id_fluxo = l.id_fluxo "
        " AND x.ordem < fe.ordem AND x.conta_revisao AND x.repetivel ORDER BY x.ordem DESC LIMIT 1) rv ON true "
        "WHERE l.id = ANY(%s) ORDER BY t.nome, folha_revisao" + (" FOR UPDATE OF l" if travar else ""),
        (list(ids),),
    )


def _item_cq(r: Dict, res: Optional[Dict], decisao: str, uf: str) -> Dict:
    """O que a decisão faz numa folha (ou por que não), para a prévia e para a execução."""
    erro = aviso = None
    if r["uf"] != uf:
        erro = "folha de outra unidade"
    elif r["fase"] != "cq":
        erro = f"a etapa atual ({r['etapa'] or 'nenhuma'}) não é de CQ"
    elif r["situacao"] == "pendente":
        erro = "o CQ ainda não começou: distribua as amostras"
    elif r["situacao"] == "pulada":
        erro = "o CQ foi pulado"
    elif r["situacao"] == "concluida" and r["resultado"]:
        erro = f"o CQ desta passagem já foi decidido ({r['resultado']})"
    elif decisao == "aprovar" and r["id_proxima"] and r["proxima_feitas"] and not r["proxima_repetivel"]:
        erro = f"a etapa {r['proxima']} não se repete neste fluxo"
    elif decisao == "nova_revisao" and not r["id_revisao"]:
        erro = "o fluxo não tem, antes do CQ, etapa que conta revisão e se repete: abra a etapa pela gaveta"
    resultado = (res or {}).get("resultado", "sem_planos")
    if not erro:
        avisos = []
        if decisao == "aprovar" and resultado == "reprovado":
            avisos.append("reprovada no CQ: aprovar assim mesmo pede a sua confirmação e fica no histórico")
        if res and res["faltam"]:
            falta = "falta avaliar 1 amostra" if res["faltam"] == 1 else f"faltam avaliar {res['faltam']} amostras"
            avisos.append(f"{falta}: decidir agora encerra o CQ com o que foi avaliado")
        if resultado == "sem_ac":
            avisos.append("plano sem Ac (convertido do DF): o Feixe não tem a régua para aprovar ou reprovar")
        aviso = "; ".join(avisos) or None
    return {
        "id_lote": r["id_lote"], "folha_revisao": r["folha_revisao"], "tema": r["tema"],
        "id_lote_etapa": r["id_lote_etapa"], "etapa": r["etapa"], "concluir": r["situacao"] == "em_andamento",
        "resultado": resultado, "frase": (res or {}).get("frase", ""), "resumo": (res or {}).get("resumo", ""),
        "faltam": (res or {}).get("faltam", 0),
        "proxima": (r["proxima"] if decisao == "aprovar" else r["revisao_etapa"]),
        "nova_folha": r["nova_folha"] if decisao == "nova_revisao" else None,
        "autores": sorted(r["autores"] or []), "aviso": aviso, "erro": erro,
    }  # fmt: skip


def previa_cq(ex: Executor, uf: str, ids: List[int], decisao: str) -> Dict:
    """O que Aprovar ou Nova revisão faz em cada folha marcada: o resultado com a frase por elemento, a etapa que abre
    (e a folha-revisão nova, na nova revisão), avisos (reprovada, amostras sem avaliação, plano sem Ac) e recusas."""
    if decisao not in DECISOES_CQ:
        raise ErroDados("decisão do CQ: aprovar ou nova_revisao", 400)
    linhas = _alvos_cq(ex, ids, travar=False)
    res = dcq.resultados(ex, [r["id_lote_etapa"] for r in linhas if r["fase"] == "cq"])
    return {"itens": [_item_cq(r, res.get(r["id_lote_etapa"]), decisao, uf) for r in linhas]}


def _texto_cq(decisao: str, item: Dict, obs: str) -> str:
    """A linha do histórico: a decisão, o resultado por elemento e a observação do supervisor."""
    if decisao == "aprovar":
        cabeca = "Aprovada no CQ"
        if item["resultado"] == "reprovado":
            cabeca += " pelo supervisor, apesar de reprovada"
        elif item["resultado"] == "sem_ac":
            cabeca += " (plano sem Ac)"
    else:
        cabeca = "Reprovada no CQ" if item["resultado"] == "reprovado" else "Nova revisão pedida no CQ"
        if item["resultado"] == "aprovado":
            cabeca += ", apesar de aprovada"
    corpo = f": {item['resumo']}" if item["resumo"] else ""
    if item["faltam"]:
        corpo += f" ({item['faltam']} sem avaliação)"
    return f"{cabeca}{corpo}. {obs}"


def decidir_cq(
    ex: Executor, uf: str, id_lote: int, decisao: str, observacao: str, forcar: bool = False, expor: bool = False
) -> Dict:
    """Decisão do supervisor sobre o resultado do CQ de uma folha (D4), numa transação:

    - aprovar: conclui a passagem de CQ como aprovada e abre a etapa seguinte do fluxo (sem seguinte, só conclui).
      Reprovada no CQ, só com `forcar` (o supervisor confirmou o aviso);
    - nova_revisao: conclui a passagem de CQ como reprovada e abre nova passagem da etapa de revisão (a mais recente
      antes do CQ que conta revisão e se repete), na revisão seguinte, às cegas ou com as correções a fazer (`expor`,
      D-66).

    O resultado por elemento e a observação vão para o histórico. As cargas da etapa aberta saem depois, em
    `cargas.preparar` (a rota chama), como em todo abrir."""
    obs = _obs(observacao)
    if decisao not in DECISOES_CQ:
        raise ErroDados("decisão do CQ: aprovar ou nova_revisao", 400)
    linhas = _alvos_cq(ex, [id_lote], travar=True)
    if not linhas:
        raise ErroDados("folha não encontrada na sua unidade", 404)
    r = linhas[0]
    res = dcq.resultados(ex, [r["id_lote_etapa"]]).get(r["id_lote_etapa"]) if r["fase"] == "cq" else None
    item = _item_cq(r, res, decisao, uf)
    if item["erro"]:
        raise ErroDados(f"{r['folha_revisao']}: {item['erro']}")
    if decisao == "aprovar" and item["resultado"] == "reprovado" and not forcar:
        raise ErroDados(f"{r['folha_revisao']}: reprovada no CQ; para aprovar assim mesmo, confirme o aviso")
    ex.executar(
        "UPDATE mapcartacomp.lote_etapa SET resultado = %s, situacao = 'concluida', "
        "concluida_em = coalesce(concluida_em, now()), concluida_por = coalesce(concluida_por, current_user) "
        "WHERE id = %s",
        ("aprovada" if decisao == "aprovar" else "reprovada", r["id_lote_etapa"]),
    )
    _hist(ex, r["id_lote_etapa"], "cq_aprovada" if decisao == "aprovar" else "cq_reprovada",
          _texto_cq(decisao, item, obs))  # fmt: skip
    destino = r["id_proxima"] if decisao == "aprovar" else r["id_revisao"]
    if destino is None:
        return {**item, "id_lote_etapa_nova": None, "erro": None}
    e = nova_passagem(ex, uf, id_lote, destino, obs, expor_ocorrencias=expor and decisao == "nova_revisao")
    return {**item, "id_lote_etapa_nova": e["id_lote_etapa"], "erro": None}


def estado(ex: Executor, id_lote: int) -> Dict:
    """Situação do lote depois de uma ação: status nacional, etapa em que está trabalhando (a aberta, se houver; senão a
    última que terminou, concluída ou pulada, D-105 e D-107) e a sugestão de próxima etapa (só sem etapa aberta)."""
    lote = ex.um(
        "SELECT l.id, l.status_nacional, l.revisao_atual, l.id_lote_etapa_atual, le.situacao, fe.ordem, "
        "fe.nome AS etapa, l.id_fluxo FROM mapcartacomp.lote l "
        "LEFT JOIN mapcartacomp.lote_etapa le ON le.id = coalesce((SELECT x.id FROM mapcartacomp.lote_etapa x "
        f"WHERE x.id_lote = l.id AND x.situacao IN ('pendente', 'em_andamento') LIMIT 1), {_ULTIMA}) "
        "LEFT JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa WHERE l.id = %s",
        (id_lote,),
    )
    lote["sugestao"] = sugerir(ex, lote)
    return lote


def sugerir(ex: Executor, lote: Dict) -> Optional[Dict]:
    """Próxima etapa sugerida (nunca aplicada sozinha): sem passagem aberta, a seguinte na ordem do fluxo."""
    if lote.get("situacao") in ABERTAS:
        return None
    return ex.um(
        "SELECT id, nome, ordem FROM mapcartacomp.fluxo_etapa WHERE id_fluxo = %s AND ordem > coalesce(%s, 0) "
        "ORDER BY ordem LIMIT 1",
        (lote["id_fluxo"], lote.get("ordem")),
    )


def historico(ex: Executor, id_lote: int) -> List[Dict]:
    return ex.todos(
        "SELECT h.em, h.acao, h.observacao, h.por, coalesce(u.nom_usuario::text, h.por) AS por_nome, fe.nome AS etapa, "
        "le.instancia FROM mapcartacomp.lote_etapa_hist h JOIN mapcartacomp.lote_etapa le ON le.id = h.id_lote_etapa "
        "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = le.id_fluxo_etapa "
        "LEFT JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = h.por WHERE le.id_lote = %s "
        "ORDER BY h.em DESC, h.id DESC",
        (id_lote,),
    )
