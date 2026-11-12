"""Catálogo nacional (B7): temas, atividades, elementos de CQ e fases. Quem cadastra é a CCAR (gerente, D-87).

Atividade = projeto + tema + fase + padrões de geração das cargas. Atividade de CQ é tema + medida de qualidade (D-83).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import ErroDados, Executor

GERACOES = ("grade", "amostra_area", "amostra_feicao", "manual", "nenhuma")
# Lado da célula em metros (002_referencias.sql); 2500 é o sub-nível do Feixe (D-78).
NIVEIS_GRADE = (500000, 100000, 50000, 10000, 5000, 2500, 1000, 200)
_PRECISAM_GRADE = ("grade", "amostra_area")


def fases(ex: Executor) -> List[Dict]:
    return ex.todos("SELECT codigo, nome, ordem, status_nacional FROM mapcartacomp.fase ORDER BY ordem")


def temas(ex: Executor) -> List[Dict]:
    return ex.todos(
        "SELECT t.id, t.nome, t.ativo, (SELECT count(*) FROM mapcartacomp.atividade a WHERE a.id_tema = t.id) "
        "AS atividades FROM mapcartacomp.tema t ORDER BY t.nome"
    )


def elementos_cq(ex: Executor) -> List[Dict]:
    """Medidas de qualidade que o Feixe oferece no CQ (nome do SGBC, D-81)."""
    return ex.todos(
        "SELECT e.id_medidadequalidade AS id, m.nome::text AS nome, e.nucleo, e.fracao_critica, e.ativo "
        "FROM mapcartacomp.cq_elemento e JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = e.id_medidadequalidade "
        "ORDER BY e.ordem, m.nome"
    )


_EM_USO = (
    "EXISTS (SELECT 1 FROM mapcartacomp.fluxo_etapa_atividade fea "
    "JOIN mapcartacomp.fluxo_etapa fe ON fe.id = fea.id_fluxo_etapa JOIN mapcartacomp.fluxo f ON f.id = fe.id_fluxo "
    "WHERE fea.id_atividade = a.id AND f.ativo)"
)


def atividades(ex: Executor, id_atividade: Optional[int] = None) -> List[Dict]:
    sql = (
        "SELECT a.id, a.nome, a.cod_projeto, p.nom_projeto AS projeto, a.id_tema, t.nome AS tema, a.fase, "
        "f.nome AS fase_nome, a.geracao, a.grade_nivel, a.id_medidadequalidade, m.nome::text AS medida, a.ativo, "
        f"{_EM_USO} AS em_uso, "
        "EXISTS (SELECT 1 FROM mapcartacomp.carga_trabalho c WHERE c.id_atividade = a.id) AS tem_cargas "
        "FROM mapcartacomp.atividade a JOIN mapcartacomp.tema t ON t.id = a.id_tema "
        "JOIN mapcartacomp.fase f ON f.codigo = a.fase JOIN mapcartctrl.t_projeto p ON p.cod_projeto = a.cod_projeto "
        "LEFT JOIN mapcartctrl.t_qua_medidadequalidade m ON m.id = a.id_medidadequalidade"
    )
    params: tuple = ()
    if id_atividade is not None:
        sql += " WHERE a.id = %s"
        params = (id_atividade,)
    return ex.todos(sql + " ORDER BY p.nom_projeto, t.nome, f.ordem, a.nome", params)


def _validar(ex: Executor, a: Dict) -> None:
    if not (a.get("nome") or "").strip():
        raise ErroDados("dê um nome à atividade", 400)
    if a.get("geracao") not in GERACOES:
        raise ErroDados(f"geração deve ser uma de: {', '.join(GERACOES)}", 400)
    nivel = a.get("grade_nivel")
    if nivel is not None and nivel not in NIVEIS_GRADE:
        raise ErroDados("nível da grade estatística desconhecido", 400)
    if a["geracao"] in _PRECISAM_GRADE and nivel is None:
        raise ErroDados("cargas pela grade ou amostra por área precisam do nível da grade", 400)
    if not ex.um("SELECT 1 FROM mapcartacomp.fase WHERE codigo = %s", (a.get("fase"),)):
        raise ErroDados("fase desconhecida", 400)
    if not ex.um("SELECT 1 FROM mapcartacomp.tema WHERE id = %s AND ativo", (a.get("id_tema"),)):
        raise ErroDados("tema desconhecido ou inativo", 400)
    if not ex.um("SELECT 1 FROM mapcartctrl.t_projeto WHERE cod_projeto = %s", (a.get("cod_projeto"),)):
        raise ErroDados("projeto desconhecido", 400)
    medida = a.get("id_medidadequalidade")
    if (a["fase"] == "cq") != (medida is not None):
        raise ErroDados("atividade de CQ precisa de uma medida de qualidade, e só ela", 400)
    if medida is not None and not ex.um(
        "SELECT 1 FROM mapcartacomp.cq_elemento WHERE id_medidadequalidade = %s AND ativo", (medida,)
    ):
        raise ErroDados("medida fora do catálogo de CQ do Feixe", 400)


def _nome_livre(ex: Executor, cod_projeto: int, nome: str, exceto: Optional[int] = None) -> None:
    if ex.um(
        "SELECT 1 FROM mapcartacomp.atividade WHERE cod_projeto = %s AND nome = %s AND id <> coalesce(%s, -1)",
        (cod_projeto, nome, exceto),
    ):
        raise ErroDados(f"já existe a atividade {nome} neste projeto")


CAMPOS = ("cod_projeto", "id_tema", "fase", "nome", "geracao", "grade_nivel", "id_medidadequalidade", "ativo")


def criar_atividade(ex: Executor, a: Dict) -> Dict:
    a = {k: a.get(k) for k in CAMPOS}
    a["nome"] = (a["nome"] or "").strip()
    a["ativo"] = a["ativo"] is not False
    _validar(ex, a)
    _nome_livre(ex, a["cod_projeto"], a["nome"])
    novo = ex.um(
        f"INSERT INTO mapcartacomp.atividade ({', '.join(CAMPOS)}) VALUES ({', '.join(['%s'] * len(CAMPOS))}) "
        "RETURNING id",
        tuple(a[k] for k in CAMPOS),
    )
    return atividades(ex, novo["id"])[0]


def alterar_atividade(ex: Executor, id_atividade: int, mudancas: Dict) -> Dict:
    """Muda nome, geração, nível da grade e ativo à vontade. Projeto, tema, fase e medida só enquanto a atividade não
    tem carga nem está numa etapa de fluxo (as cargas e etapas dependem deles). Inativar só fora de fluxo ativo."""
    atual = (atividades(ex, id_atividade) or [None])[0]
    if atual is None:
        raise ErroDados("atividade não encontrada", 404)
    novo = {k: mudancas.get(k, atual[k]) for k in CAMPOS}
    novo["nome"] = (novo["nome"] or "").strip()
    estruturais = [k for k in ("cod_projeto", "id_tema", "fase", "id_medidadequalidade") if novo[k] != atual[k]]
    if estruturais and (atual["em_uso"] or atual["tem_cargas"]):
        raise ErroDados("projeto, tema, fase e medida não mudam em atividade com cargas ou usada em fluxo: crie outra")
    if atual["ativo"] and novo["ativo"] is False and atual["em_uso"]:
        raise ErroDados("a atividade está numa etapa de fluxo ativo: tire-a do fluxo antes de inativar")
    _validar(ex, novo)
    _nome_livre(ex, novo["cod_projeto"], novo["nome"], id_atividade)
    ex.executar(
        f"UPDATE mapcartacomp.atividade SET {', '.join(f'{k} = %s' for k in CAMPOS)} WHERE id = %s",
        tuple(novo[k] for k in CAMPOS) + (id_atividade,),
    )
    return atividades(ex, id_atividade)[0]


def criar_tema(ex: Executor, nome: str) -> Dict:
    nome = (nome or "").strip()
    if not nome:
        raise ErroDados("dê um nome ao tema", 400)
    if ex.um("SELECT 1 FROM mapcartacomp.tema WHERE lower(nome) = lower(%s)", (nome,)):
        raise ErroDados(f"já existe o tema {nome}")
    return ex.um("INSERT INTO mapcartacomp.tema (nome) VALUES (%s) RETURNING id, nome, ativo", (nome,))


def alterar_tema(ex: Executor, id_tema: int, nome: Optional[str] = None, ativo: Optional[bool] = None) -> Dict:
    atual = ex.um("SELECT id, nome, ativo FROM mapcartacomp.tema WHERE id = %s", (id_tema,))
    if not atual:
        raise ErroDados("tema não encontrado", 404)
    nome = (nome if nome is not None else atual["nome"]).strip()
    if not nome:
        raise ErroDados("dê um nome ao tema", 400)
    if ex.um("SELECT 1 FROM mapcartacomp.tema WHERE lower(nome) = lower(%s) AND id <> %s", (nome, id_tema)):
        raise ErroDados(f"já existe o tema {nome}")
    if ativo is False and ex.um("SELECT 1 FROM mapcartacomp.atividade WHERE id_tema = %s AND ativo", (id_tema,)):
        raise ErroDados("o tema tem atividades ativas: inative-as antes")
    return ex.um(
        "UPDATE mapcartacomp.tema SET nome = %s, ativo = %s WHERE id = %s RETURNING id, nome, ativo",
        (nome, atual["ativo"] if ativo is None else ativo, id_tema),
    )
