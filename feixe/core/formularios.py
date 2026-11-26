"""Formulário, dica do mapa, título no identificar e ações de cada camada do Feixe no QGIS, por usuário (D-102).

Cada pessoa vê só o que usa: o APM (Minhas cargas, Minhas folhas) vê situação, folha e progresso; o supervisor (cargas
e folhas da unidade) vê responsável, situação, andamento e CQ. Ids, uuid e datas cruas ficam fora do formulário. Tudo
com recursos nativos do QGIS (formulário em arrastar e soltar, campos de expressão, dicas de mapa e ações Python que
chamam o plugin), configurados ao montar as camadas. Roda na thread principal.
"""

from __future__ import annotations

from typing import List, Tuple, Union

from qgis.core import (
    QgsAction,
    QgsAttributeEditorContainer,
    QgsAttributeEditorField,
    QgsEditFormConfig,
    QgsExpression,
    QgsField,
    QgsOptionalExpression,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QVariant

# Situação da etapa no banco -> texto da tela.
_SITUACAO = (
    "CASE WHEN \"{c}\" = 'pendente' THEN 'a iniciar' WHEN \"{c}\" = 'em_andamento' THEN 'em andamento' "
    "WHEN \"{c}\" = 'concluida' THEN 'concluída' ELSE \"{c}\" END"
)
_DIAS = 'to_int((epoch(now()) - epoch("{c}")) / 86400000)'


def _quando_concluida() -> str:
    dias = _DIAS.format(c="concluido_em")
    return (
        "CASE WHEN \"concluido\" THEN 'concluída em ' || format_date(\"concluido_em\", 'dd/MM/yyyy HH:mm') || "
        f"CASE WHEN {dias} = 0 THEN ' (hoje)' WHEN {dias} = 1 THEN ' (ontem)' "
        f"ELSE ' (há ' || {dias} || ' dias)' END ELSE 'pendente' END"
    )


def _campo_expressao(camada: QgsVectorLayer, nome: str, rotulo: str, expressao: str) -> None:
    camada.addExpressionField(expressao, QgsField(nome, QVariant.String))
    camada.setFieldAlias(camada.fields().indexOf(nome), rotulo)


# Item do formulário: nome de campo, ou (título do grupo, [itens], visível quando, recolhido).
Item = Union[str, Tuple]


def _formulario(
    camada: QgsVectorLayer, grupos: List[Tuple], editaveis: Tuple[str, ...] = (), acoes: Tuple = ()
) -> None:
    """Formulário em grupos (arrastar e soltar), só com os campos listados; o resto fica fora. Só `editaveis` editam.
    `acoes` (QgsAction já na camada) viram botões num grupo "Ações" no fim, onde o QGIS tem o widget de ação no
    formulário (`QgsAttributeEditorAction`); sem ele, continuam no menu de ações do identificar e do clique direito."""
    cfg = camada.editFormConfig()
    cfg.setLayout(QgsEditFormConfig.TabLayout)
    cfg.clearTabs()
    raiz = cfg.invisibleRootContainer()
    aba = QgsAttributeEditorContainer(camada.name(), raiz)
    for titulo, campos, visivel, recolhido in grupos:
        g = QgsAttributeEditorContainer(titulo, aba)
        g.setIsGroupBox(True)
        if visivel:
            g.setVisibilityExpression(QgsOptionalExpression(QgsExpression(visivel)))
        if recolhido and hasattr(g, "setCollapsed"):
            g.setCollapsed(True)
        for nome in campos:
            g.addChildElement(QgsAttributeEditorField(nome, camada.fields().indexOf(nome), g))
        aba.addChildElement(g)
    if acoes:
        try:
            from qgis.core import QgsAttributeEditorAction
        except ImportError:  # QGIS sem o widget de ação no formulário
            QgsAttributeEditorAction = None  # noqa: N806
        if QgsAttributeEditorAction is not None:
            g = QgsAttributeEditorContainer("Ações", aba)
            g.setIsGroupBox(True)
            for a in acoes:
                g.addChildElement(QgsAttributeEditorAction(a, g))
            aba.addChildElement(g)
    cfg.addTab(aba)
    for i, f in enumerate(camada.fields()):
        cfg.setReadOnly(i, f.name() not in editaveis)
    camada.setEditFormConfig(cfg)


def _acao(camada: QgsVectorLayer, titulo: str, chamada: str) -> QgsAction:
    """Ação Python da camada (clique direito no formulário, identificar e tabela; ferramenta de ações no mapa)."""
    codigo = f"from qgis.utils import plugins\nplugins['feixe'].{chamada}"
    acao = QgsAction(QgsAction.GenericPython, titulo, codigo, "", False, titulo, {"Feature", "Canvas", "Form"})
    camada.actions().addAction(acao)
    return acao


# --- APM: Minhas cargas -----------------------------------------------------------------------------------------------
# Do workspace (C4): `id` é o id da carga na CCAR; folha, tema, etapa, atividade e as contagens vêm da view juntada
# (`vw_minhas_cargas_info`), com as contagens em texto (a view não tipa expressão: daí o `to_int`).
def minhas_cargas(camada: QgsVectorLayer) -> None:
    _campo_expressao(camada, "situacao_txt", "Situação", _quando_concluida())
    _campo_expressao(camada, "folha_txt", "Folha", '"folha_revisao" || \' · \' || "tema"')
    _campo_expressao(
        camada, "progresso_txt", "Minhas cargas na folha",
        "to_int(\"minhas_concluidas_na_folha\") || ' de ' || to_int(\"minhas_na_folha\") || ' concluídas (' || "
        "round(100.0 * to_int(\"minhas_concluidas_na_folha\") / to_int(\"minhas_na_folha\")) || '%)'",
    )  # fmt: skip
    camada.setFieldAlias(camada.fields().indexOf("concluido"), "Concluída")
    camada.setFieldAlias(camada.fields().indexOf("atividade"), "Atividade")
    camada.setFieldAlias(camada.fields().indexOf("etapa"), "Etapa")
    camada.setFieldAlias(camada.fields().indexOf("id"), "Carga nº")
    _formulario(
        camada,
        [
            ("Situação", ["concluido", "situacao_txt"], None, False),
            ("Folha", ["folha_txt", "etapa", "progresso_txt"], None, False),
            ("Detalhes", ["atividade", "id"], None, True),
        ],
        editaveis=("concluido",),
    )
    camada.setDisplayExpression("'Carga · ' || \"folha_revisao\"")
    camada.setMapTipTemplate(
        "<b>[% \"folha_revisao\" %]</b> · carga [% CASE WHEN \"concluido\" THEN 'concluída' ELSE 'pendente' END %]"
        '<br>Minhas na folha: [% to_int("minhas_concluidas_na_folha") %] de [% to_int("minhas_na_folha") %]'
    )
    _acao(camada, "Trabalhar nesta carga", 'trabalhar_em([% "id" %])')
    _acao(camada, "Pular esta carga", 'pular_carga([% "id" %])')


# --- APM: Minhas folhas -----------------------------------------------------------------------------------------------
def minhas_folhas(camada: QgsVectorLayer, id_camada_minhas: str) -> None:
    """`id_camada_minhas`: a camada Minhas cargas do mesmo subgrupo, para contar as cargas da pessoa na folha. Do
    workspace (C4), que só tem as cargas da pessoa: a folha toda (todas as cargas, o responsável principal) fica na
    supervisão, que lê a CCAR."""
    contar = (
        "aggregate(layer:='{id}', aggregate:='count', expression:=\"id\", "
        "filter:=\"id_lote\" = attribute(@parent, 'id_lote'){extra})"
    )
    total = contar.format(id=id_camada_minhas, extra="")
    feitas = contar.format(id=id_camada_minhas, extra=' AND "concluido"')
    _campo_expressao(camada, "minhas_txt", "Minhas cargas", f"{feitas} || ' de ' || {total} || ' concluídas'")
    _campo_expressao(camada, "etapa_txt", "Etapa", f"\"etapa\" || ' · ' || {_SITUACAO.format(c='situacao')}")
    camada.setFieldAlias(camada.fields().indexOf("folha_revisao"), "Folha")
    camada.setFieldAlias(camada.fields().indexOf("tema"), "Tema")
    _formulario(
        camada,
        [
            ("Folha", ["folha_revisao", "tema", "etapa_txt"], None, False),
            ("Andamento", ["minhas_txt"], None, False),
        ],
    )
    camada.setDisplayExpression("'Folha · ' || \"folha_revisao\"")
    camada.setMapTipTemplate(f'<b>[% "folha_revisao" %]</b> · [% "tema" %]<br>Minhas: [% {feitas} %] de [% {total} %]')
    _acao(camada, "Próxima carga nesta folha", 'proxima_na_folha([% "id_lote" %])')


# --- Supervisor: cargas por responsável e a atribuir ------------------------------------------------------------------
def cargas_supervisao(camada: QgsVectorLayer) -> None:
    _campo_expressao(
        camada, "responsavel_txt", "Responsável",
        "coalesce(\"responsavel_nome\" || ' (' || \"responsavel\" || ')', 'a atribuir')",
    )  # fmt: skip
    _campo_expressao(camada, "situacao_txt", "Situação", _quando_concluida())
    _campo_expressao(camada, "folha_txt", "Folha", '"folha_revisao" || \' · \' || "tema"')
    _campo_expressao(camada, "etapa_txt", "Etapa", f"\"etapa\" || ' · ' || {_SITUACAO.format(c='situacao_etapa')}")
    for campo, rotulo in (("atividade", "Atividade"), ("geocodigo", "Geocódigo da célula"), ("criado_em", "Criada em")):
        camada.setFieldAlias(camada.fields().indexOf(campo), rotulo)
    _formulario(
        camada,
        [
            ("Carga", ["responsavel_txt", "situacao_txt"], None, False),
            ("Folha", ["folha_txt", "atividade", "etapa_txt"], None, False),
            ("Detalhes", ["geocodigo", "criado_em"], None, True),
        ],
    )
    camada.setDisplayExpression("coalesce(\"responsavel_nome\", 'A atribuir') || ' · ' || \"folha_revisao\"")
    camada.setMapTipTemplate(
        '<b>[% coalesce("responsavel_nome", \'A atribuir\') %]</b> · [% "folha_revisao" %] · '
        "[% CASE WHEN \"concluido\" THEN 'concluída' ELSE 'pendente' END %]"
    )
    _acao(camada, "Abrir a folha no Feixe", 'abrir_folha([% "id_lote" %])')


# --- Supervisor: folhas -----------------------------------------------------------------------------------------------
def folhas_supervisao(camada: QgsVectorLayer) -> None:
    _campo_expressao(camada, "etapa_txt", "Etapa atual", f"\"etapa\" || ' · ' || {_SITUACAO.format(c='situacao')}")
    _campo_expressao(
        camada, "cargas_txt", "Cargas",
        "\"cargas_concluidas\" || ' de ' || \"cargas_total\" || ' concluídas (' || "
        "coalesce(round(\"perc_concluidas\"), 0) || '%)'",
    )  # fmt: skip
    _campo_expressao(
        camada, "inicio_txt", "Início",
        f"format_date(\"inicio\", 'dd/MM/yyyy') || ' (há ' || {_DIAS.format(c='inicio')} || ' dias)'",
    )  # fmt: skip
    _campo_expressao(
        camada, "ocorrencias_txt", "Ocorrências tratadas", '"ocorrencias_tratadas" || \' de \' || "ocorrencias"'
    )
    _campo_expressao(camada, "tipo_txt", "Tipo", "CASE WHEN \"tipo\" = 'folha' THEN 'folha' ELSE 'lote livre' END")
    for campo, rotulo in (
        ("folha_revisao", "Folha"), ("tema", "Tema"), ("status_nacional", "Status nacional"),
        ("responsavel_nome", "Responsável principal"), ("ultimo_cq_folha_revisao", "Último CQ"),
        ("ultimo_cq_resultado", "Resultado"),
    ):  # fmt: skip
        camada.setFieldAlias(camada.fields().indexOf(campo), rotulo)
    _formulario(
        camada,
        [
            ("Folha", ["folha_revisao", "tema", "tipo_txt"], None, False),
            ("Andamento", ["etapa_txt", "status_nacional", "inicio_txt"], None, False),
            ("Cargas", ["cargas_txt", "responsavel_nome"], None, False),
            (
                "Último CQ", ["ultimo_cq_folha_revisao", "ultimo_cq_resultado", "ocorrencias_txt"],
                "\"ultimo_cq_resultado\" IS NOT NULL OR \"ocorrencias\" > 0", False,
            ),
        ],
    )  # fmt: skip
    camada.setDisplayExpression("'Folha · ' || \"folha_revisao\"")
    camada.setMapTipTemplate(
        '<b>[% "folha_revisao" %]</b> · [% "etapa" %] ([% ' + _SITUACAO.format(c="situacao") + " %])"
        '<br>[% "cargas_concluidas" %] de [% "cargas_total" %] cargas · '
        "[% coalesce(\"responsavel_nome\", 'sem responsável') %]"
    )
    _acao(camada, "Abrir no Feixe", 'abrir_folha([% "id_lote" %])')


# --- CQ: amostras do avaliador (D3c) ----------------------------------------------------------------------------------
# A camada é a `carga_trabalho` do workspace (as minhas cargas de CQ) com a view `vw_minhas_amostras_info` juntada pelo
# `id`; tudo só leitura (a camada também): avaliar é ação da camada e da barra, que vão pela outbox (D-127).
_STATUS_AMOSTRA = (
    "CASE WHEN \"status\" IS NULL THEN 'pendente' WHEN to_int(\"status\") = 1 THEN 'conforme' ELSE 'não conforme' END"
)


def amostras(camada: QgsVectorLayer) -> None:
    dias = _DIAS.format(c="avaliado_em")
    _campo_expressao(
        camada, "status_txt", "Situação",
        f"{_STATUS_AMOSTRA} || CASE WHEN \"avaliado_em\" IS NOT NULL THEN ' em ' || "
        f"format_date(\"avaliado_em\", 'dd/MM/yyyy HH:mm') || CASE WHEN {dias} = 0 THEN ' (hoje)' "
        f"WHEN {dias} = 1 THEN ' (ontem)' ELSE ' (há ' || {dias} || ' dias)' END ELSE '' END",
    )  # fmt: skip
    _campo_expressao(camada, "folha_txt", "Folha", '"folha_revisao" || \' · \' || "tema"')
    _campo_expressao(
        camada, "plano_txt", "Plano",
        "'n = ' || to_int(\"plano_n\") || ', Ac = ' || to_int(\"plano_ac\") || "
        "coalesce(' (letra ' || \"plano_letra\" || ', nível ' || \"plano_nivel\" || ', LQA ' || "
        "format_number(\"plano_lqa\", 1) || '%)', '')",
    )  # fmt: skip
    _campo_expressao(
        camada, "progresso_txt", "Minhas amostras na folha",
        "to_int(\"avaliadas_na_folha\") || ' de ' || to_int(\"amostras_na_folha\") || ' avaliadas'",
    )  # fmt: skip
    _campo_expressao(
        camada, "ocorrencias_txt", "Ocorrências",
        "CASE WHEN to_int(\"ocorrencias\") = 0 THEN 'nenhuma' WHEN to_int(\"ocorrencias\") = 1 THEN '1 ocorrência' "
        "ELSE to_int(\"ocorrencias\") || ' ocorrências' END",
    )  # fmt: skip
    for campo, rotulo in (("elemento", "Elemento"), ("observacao", "Observação"), ("etapa", "Etapa"),
                          ("geocodigo", "Geocódigo da célula"), ("id", "Carga nº")):  # fmt: skip
        camada.setFieldAlias(camada.fields().indexOf(campo), rotulo)
    acoes = (
        _acao(camada, "Trabalhar nesta amostra", 'trabalhar_na_amostra([% "id" %])'),
        _acao(camada, "Conforme", 'avaliar_amostra([% "id" %], 1)'),
        _acao(camada, "Não conforme…", 'nao_conforme([% "id" %])'),
    )
    _formulario(
        camada,
        [
            ("Amostra", ["elemento", "status_txt", "observacao", "ocorrencias_txt"], None, False),
            ("Folha", ["folha_txt", "etapa", "plano_txt", "progresso_txt"], None, False),
            ("Detalhes", ["geocodigo", "id"], None, True),
        ],
        acoes=acoes,
    )
    camada.setDisplayExpression("'Amostra · ' || \"elemento\" || ' · ' || \"folha_revisao\"")
    camada.setMapTipTemplate(
        f'<b>[% "folha_revisao" %]</b> · [% "elemento" %] · [% {_STATUS_AMOSTRA} %]'
        '<br>Plano: n = [% to_int("plano_n") %], Ac = [% to_int("plano_ac") %] · '
        '[% to_int("avaliadas_na_folha") %] de [% to_int("amostras_na_folha") %] avaliadas'
    )


def folhas_cq(camada: QgsVectorLayer) -> None:
    """Minhas folhas no subgrupo do CQ: a moldura das folhas em avaliação, só com folha, tema e etapa."""
    _campo_expressao(camada, "etapa_txt", "Etapa", f"\"etapa\" || ' · ' || {_SITUACAO.format(c='situacao')}")
    camada.setFieldAlias(camada.fields().indexOf("folha_revisao"), "Folha")
    camada.setFieldAlias(camada.fields().indexOf("tema"), "Tema")
    _formulario(camada, [("Folha", ["folha_revisao", "tema", "etapa_txt"], None, False)])
    camada.setDisplayExpression("'Folha · ' || \"folha_revisao\"")
    camada.setMapTipTemplate('<b>[% "folha_revisao" %]</b> · [% "tema" %] · [% "etapa" %]')


# --- CQ: ocorrências (D3c) --------------------------------------------------------------------------------------------
# A camada é a `cq_inspecao` do workspace, com a view `vw_ocorrencias_info` juntada pelo `uuid` (a registrada offline
# ainda não tem id da CCAR). Do avaliador (`ocorrencias`): só a anotação edita, e a gravação sai do buffer do QGIS e
# vai pela outbox (`core/edicao.py`). Para ciência (o APM autor) e correção (a revisão com "incluir correções"): tudo só
# leitura; o Ciente é ação.
def ocorrencias(camada: QgsVectorLayer, papel: str) -> None:
    _campo_expressao(camada, "folha_txt", "Folha", "\"folha_revisao\" || coalesce(' · ' || \"tema\", '')")
    _campo_expressao(
        camada, "amostra_txt", "Amostra",
        "coalesce('célula ' || \"amostra_geocodigo\", 'carga ' || to_int(\"id_carga_amostra\"), '—')",
    )  # fmt: skip
    _campo_expressao(
        camada, "registrada_txt", "Registrada",
        "coalesce(\"responsavel\", '') || coalesce(' em ' || format_date(\"criado_em\", 'dd/MM/yyyy HH:mm'), "
        "' (ainda não enviada)')",
    )  # fmt: skip
    _campo_expressao(
        camada, "ciencia_txt", "Ciência",
        "CASE WHEN \"ciente_em\" IS NULL THEN 'ainda sem ciência' "
        "ELSE 'ciente em ' || format_date(\"ciente_em\", 'dd/MM/yyyy HH:mm') END",
    )  # fmt: skip
    for campo, rotulo in (("anotacao", "Anotação"), ("elemento", "Elemento"), ("responsavel", "Avaliador")):
        camada.setFieldAlias(camada.fields().indexOf(campo), rotulo)
    acoes: Tuple = ()
    if papel == "ocorrencias":
        grupos = [
            ("Ocorrência", ["anotacao"], None, False),
            ("Onde", ["elemento", "folha_txt", "amostra_txt"], None, False),
            ("Detalhes", ["registrada_txt", "ciencia_txt"], None, True),
        ]
        editaveis: Tuple[str, ...] = ("anotacao",)
    else:
        grupos = [
            ("Ocorrência", ["anotacao", "elemento"], None, False),
            ("Onde", ["folha_txt", "amostra_txt"], None, False),
            ("Avaliação", ["responsavel", "registrada_txt", "ciencia_txt"], None, False),
        ]
        editaveis = ()
        if papel == "ocorrencias_ciencia":
            acoes = (_acao(camada, "Ciente", "ciente('[% \"uuid\" %]')"),)
    _formulario(camada, grupos, editaveis=editaveis, acoes=acoes)
    camada.setDisplayExpression("'Ocorrência · ' || \"elemento\" || ' · ' || \"folha_revisao\"")
    camada.setMapTipTemplate(
        '<b>[% "elemento" %]</b> · [% "folha_revisao" %]<br>[% coalesce("anotacao", \'(sem anotação)\') %]'
    )
