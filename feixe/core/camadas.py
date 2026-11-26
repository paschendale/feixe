"""Camadas do Feixe no projeto aberto do QGIS: o grupo "Feixe", organizado por tarefa (D-101).

A execução lê o workspace local (C4, D-111): as camadas de quem executa abrem o GeoPackage pelo OGR, funcionam
offline e mostram na hora o que a pessoa fez (a conclusão local, antes do push). A supervisão lê a CCAR, com a mesma
credencial do Authentication Manager (authcfg). Roda na thread principal (mexe no projeto e na árvore de camadas).

Dois subgrupos, um por modo de trabalho; só um fica ligado (a barra troca o modo, sem recarregar):

Execução (todos), do workspace:
- Minhas cargas: a tabela `carga_trabalho` do workspace, filtrada pela conta do workspace e pelas passagens abertas,
  com a folha, a etapa, a atividade e o progresso da pessoa vindos da view `vw_minhas_cargas_info` (junção pelo `id`,
  em memória, renovada a cada recarga). Feita para ficar ligada o dia todo sobre a imagem (D-101): a carga atual (a
  da barra: próxima, concluir, zoom do painel) só com contorno duplo magenta com halo branco, para ver a imagem
  inteira dentro dela; pendentes com hachura espaçada azul-clara; concluídas há até 3 dias com hachura verde mais
  densa; concluídas antes, hachura cruzada cinza-clara. Cores claras e saturadas porque a imagem por baixo é escura
  (vegetação, solo, água). Só `concluido` é editável, e a edição não vai pelo OGR: sai do buffer do QGIS no commit e
  passa pelas regras da execução e pela outbox (`core/edicao.py`).
- Minhas folhas: a view `vw_minhas_folhas` (só leitura), moldura e rótulo das folhas em que a pessoa tem cargas de
  passagens abertas.
- CQ (D3c), num subgrupo "CQ · tema": por elemento (uma atividade de CQ por medida), Ocorrências - <elemento> (os
  pontos de `cq_inspecao` nas minhas amostras, pino com a anotação curta) e Amostras - <elemento> (as minhas cargas de
  CQ com o status da amostra pela view juntada `vw_minhas_amostras_info`: pendente, conforme, não conforme; a amostra
  atual só com o contorno magenta com halo, como a carga atual). Só o primeiro elemento vem ligado. A avaliação não
  passa pelo buffer do QGIS: Amostras é só leitura, e Conforme e Não conforme são ações da camada e da barra.
- Ocorrências para ciência (o APM): as que apontam uma carga minha, ainda sem ciência; só quando houver alguma.
  Correções a fazer: na revisão planejada com "incluir correções a serem feitas", as não tratadas da folha.

Supervisão (só supervisor, e só com a CCAR respondendo), das passagens abertas dos lotes da UF:
- Cargas por responsável: uma cor bem distinta por pessoa, estável entre uma montagem e outra.
- Cargas a atribuir: sem responsável, esperando o supervisor; sem as amostras de CQ (fase D).
- Folhas: subgrupo com uma camada por tema ("Folhas · Hidrografia"...), de `ctrl_lote` da UF, rotulada
  "MI-revisão · responsável · etapa", com o estilo da articulação do DF. A mesma folha tem um lote por tema; numa
  camada só, os rótulos dos temas se sobrepunham. Só o tema com mais folhas fica ligado.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from qgis.core import (
    QgsDataSourceUri,
    QgsExpressionContextUtils,
    QgsFeatureRequest,
    QgsFillSymbol,
    QgsLayerTreeGroup,
    QgsLinePatternFillSymbolLayer,
    QgsLineSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRuleBasedRenderer,
    QgsSimpleFillSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorLayer,
    QgsVectorLayerJoinInfo,
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from .ambiente import Ambiente
from .dados.cargas import SQL_PASSAGENS_ATUAIS
from .dados.local import SQL_ABERTAS
from .dados.local import grupos as lgrupos

GRUPO = "Feixe"
PASTA_ESTILOS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "estilos")
_UF = re.compile(r"^[A-Z]{2}$")


def _uri(amb: Ambiente, authcfg: str, tabela: str, chave: str, filtro: str = "") -> str:
    u = QgsDataSourceUri()
    u.setConnection(amb.host, str(amb.porta), amb.banco, "", "", _modo_ssl(amb.sslmode), authcfg)
    u.setDataSource("mapcartacomp", tabela, "geom", filtro, chave)
    u.setSrid("4674")
    u.setWkbType(QgsWkbTypes.MultiPolygon)
    return u.uri(False)


def _modo_ssl(sslmode: Optional[str]):
    return {
        "disable": QgsDataSourceUri.SslDisable,
        "allow": QgsDataSourceUri.SslAllow,
        "require": QgsDataSourceUri.SslRequire,
        "verify-ca": QgsDataSourceUri.SslVerifyCa,
        "verify-full": QgsDataSourceUri.SslVerifyFull,
    }.get(sslmode or "", QgsDataSourceUri.SslPrefer)


def _filtro_uf(uf: Optional[str], coluna: str = "uf") -> str:
    # A UF vem do SGBC e é validada aqui antes de entrar no filtro da camada (que não aceita parâmetros).
    if uf and _UF.match(uf):
        return f"{coluna} = '{uf}'"
    return ""


def _filtro_passagens(uf: Optional[str]) -> str:
    sub = SQL_PASSAGENS_ATUAIS + (f" AND {_filtro_uf(uf, 'l.uf')}" if _filtro_uf(uf) else "")
    partes = [p for p in (_filtro_uf(uf), f"id_lote_etapa IN ({sub})") if p]
    return " AND ".join(partes)


def _camada(amb, authcfg, nome, tabela, chave, filtro="", estilo=None) -> QgsVectorLayer:
    camada = QgsVectorLayer(_uri(amb, authcfg, tabela, chave, filtro), nome, "postgres")
    if not camada.isValid():
        raise RuntimeError(f"camada '{nome}' inválida: {camada.dataProvider().error().message()}")
    if estilo:
        msg, ok = camada.loadNamedStyle(os.path.join(PASTA_ESTILOS, estilo))
        if not ok:
            raise RuntimeError(f"estilo {estilo}: {msg}")
    return camada


# --- camadas do workspace (C4) ----------------------------------------------------------------------------------------
VW_CARGA_INFO, VW_MINHAS_FOLHAS = "vw_minhas_cargas_info", "vw_minhas_folhas"  # as views de sync/esquema.py
VW_AMOSTRA_INFO, VW_OCORRENCIA_INFO = "vw_minhas_amostras_info", "vw_ocorrencias_info"
_EU = "(SELECT valor FROM meta WHERE chave = 'usuario')"  # a conta do workspace, sem citar nada no filtro
# Colunas técnicas do espelho, fora da tabela de atributos (o formulário já mostra só o que a pessoa usa).
_OCULTAS = {
    "fid", "uuid", "id_lote_etapa", "id_atividade", "id_cq_plano", "uf", "responsavel", "geocodigo", "criado_em",
    "criado_por", "atualizado_em", "atualizado_por", "xmin", "ymin", "xmax", "ymax", "cx", "cy", "versao_base", "sujo",
    "id_lote", "situacao_etapa", "minhas_na_folha", "minhas_concluidas_na_folha",
    # CQ (D3c)
    "id_amostra", "id_carga_trabalho", "id_carga_avaliada", "id_carga_amostra", "tratado_por", "ciente_por",
    "situacao_cq", "amostras_na_folha", "avaliadas_na_folha", "plano_letra", "plano_nivel", "plano_lqa",
}  # fmt: skip


def _camada_gpkg(gpkg: str, tabela: str, nome: str, filtro: str = "") -> QgsVectorLayer:
    camada = QgsVectorLayer(f"{gpkg}|layername={tabela}", nome, "ogr")
    if filtro and camada.isValid():
        camada.setSubsetString(filtro)
    if not camada.isValid():
        raise RuntimeError(f"camada '{nome}' do espaço de trabalho inválida: {camada.dataProvider().error().message()}")
    return camada


def do_workspace(camada) -> bool:
    return isinstance(camada, QgsVectorLayer) and camada.providerType() == "ogr"


EDITAVEIS = ("minhas_cargas", "ocorrencias")  # papéis cuja edição vai pela outbox (`core/edicao.py`)


def editavel_pelo_feixe(camada) -> bool:
    """Minhas cargas e as ocorrências do avaliador, do workspace: a edição delas vai pela outbox
    (`core/edicao.py`)."""
    return do_workspace(camada) and camada.customProperty(_PAPEL) in EDITAVEIS


def papel(camada) -> Optional[str]:
    return camada.customProperty(_PAPEL) if isinstance(camada, QgsVectorLayer) else None


def _filtro_minhas(atividades: Optional[List[int]] = None) -> str:
    """Minhas cargas de passagens abertas (e das atividades do subgrupo), sobre o workspace. As cargas de CQ (as
    amostras) ficam nas camadas do CQ."""
    extra = f" AND id_atividade IN ({_em(atividades)})" if atividades else ""
    return (
        f"responsavel = {_EU} AND id_cq_plano IS NULL "
        f"AND id_lote_etapa IN (SELECT id FROM lote_etapa WHERE situacao IN {SQL_ABERTAS}){extra}"
    )


def _filtro_minhas_folhas(atividades: Optional[List[int]] = None) -> str:
    """A view já tem só as folhas com cargas minhas abertas; com subgrupos, só as da atividade."""
    if not atividades:
        return ""
    return (
        "id_lote IN (SELECT le.id_lote FROM carga_trabalho c JOIN lote_etapa le ON le.id = c.id_lote_etapa "
        f"WHERE c.responsavel = {_EU} AND le.situacao IN {SQL_ABERTAS} AND c.id_atividade IN ({_em(atividades)}))"
    )


def _juntar_info(camada: QgsVectorLayer, info: QgsVectorLayer, chave: str = "id") -> None:
    """Folha, etapa, atividade e progresso da pessoa na folha, da view, em memória (uma leitura da view por recarga;
    sem o cache, cada feição faria uma consulta e a tabela de atributos levaria dezenas de segundos)."""
    j = QgsVectorLayerJoinInfo()
    j.setJoinLayer(info)
    j.setJoinFieldName(chave)
    j.setTargetFieldName(chave)
    j.setPrefix("")
    j.setUsingMemoryCache(True)
    j.setEditable(False)
    camada.addJoin(j)


def _esconder_colunas(camada: QgsVectorLayer) -> None:
    cfg = camada.attributeTableConfig()
    colunas = cfg.columns()
    for c in colunas:
        c.hidden = c.name in _OCULTAS
    cfg.setColumns(colunas)
    camada.setAttributeTableConfig(cfg)


def _contar(camada: QgsVectorLayer) -> int:
    """Feições que a camada mostra. Na do workspace com filtro o `featureCount` do OGR não serve (conta a tabela)."""
    if not do_workspace(camada):
        return camada.featureCount()
    pedido = QgsFeatureRequest().setNoAttributes().setFlags(QgsFeatureRequest.NoGeometry)
    return sum(1 for _ in camada.getFeatures(pedido))


def cores_distintas(n: int) -> List[QColor]:
    """n cores bem separadas para categorias (uma por pessoa): tons pelo ângulo de ouro, alternando saturação e
    brilho para vizinhos de tom não se confundirem. Determinístico: a mesma ordem dá as mesmas cores."""
    cores = []
    for i in range(n):
        cor = QColor()
        cor.setHsv(int((i * 137.508) % 360), (200, 140, 230)[i % 3], (230, 190, 160)[(i // 3) % 3])
        cores.append(cor)
    return cores


# --- Minhas cargas: estilo e carga atual (D-101) ----------------------------------------------------------------------
VAR_ATUAL = "feixe_carga_atual"  # variável do projeto com o id da carga atual; o estilo lê dela
_ATUAL = f'coalesce("id" = to_int(@{VAR_ATUAL}), false)'


def _contorno(cor: str, largura: float, opacidade: float = 1.0) -> QgsSimpleFillSymbolLayer:
    c = QColor(cor)
    c.setAlphaF(opacidade)
    camada = QgsSimpleFillSymbolLayer()
    camada.setBrushStyle(Qt.NoBrush)
    camada.setStrokeColor(c)
    camada.setStrokeWidth(largura)
    return camada


def _hachura(cor: str, angulo: float, distancia: float, largura: float, opacidade: float):
    c = QColor(cor)
    c.setAlphaF(opacidade)
    h = QgsLinePatternFillSymbolLayer()
    h.setLineAngle(angulo)
    h.setDistance(distancia)  # mm na tela: o espaçamento não muda com o zoom
    h.setSubSymbol(QgsLineSymbol.createSimple({"color": c.name(QColor.HexArgb), "width": str(largura)}))
    return h


def _simbolo(*camadas) -> QgsFillSymbol:
    s = QgsFillSymbol()
    s.deleteSymbolLayer(0)
    for c in camadas:
        s.appendSymbolLayer(c)
    return s


def estilo_minhas(camada: QgsVectorLayer) -> None:
    """Estilo do executor, para trabalhar com a camada ligada sobre a imagem. As regras são exclusivas: a carga
    atual não leva hachura, mesmo pendente."""
    regras = [
        (
            "Carga atual",
            _ATUAL,
            _simbolo(_contorno("#FFFFFF", 2.0, 0.85), _contorno("#FF2BD6", 0.9)),
        ),
        (
            "Pendente",
            f"NOT {_ATUAL} AND NOT coalesce(\"concluido\", false)",
            _simbolo(_hachura("#5AB0FF", 45, 3.0, 0.35, 0.9), _contorno("#5AB0FF", 0.4)),
        ),
        (
            "Concluída nos últimos 3 dias",
            f"NOT {_ATUAL} AND \"concluido\" AND coalesce(\"concluido_em\" > now() - to_interval('3 days'), true)",
            _simbolo(_hachura("#3DDC6A", -45, 1.6, 0.4, 0.9), _contorno("#3DDC6A", 0.4)),
        ),
        (
            "Concluída há mais de 3 dias",
            f"NOT {_ATUAL} AND \"concluido\" AND \"concluido_em\" <= now() - to_interval('3 days')",
            _simbolo(
                _hachura("#D0D0D0", 45, 1.8, 0.3, 0.8), _hachura("#D0D0D0", -45, 1.8, 0.3, 0.8),
                _contorno("#D0D0D0", 0.3, 0.9),
            ),
        ),
    ]  # fmt: skip
    raiz = QgsRuleBasedRenderer.Rule(None)
    for rotulo, expressao, simbolo in regras:
        raiz.appendChild(QgsRuleBasedRenderer.Rule(simbolo, 0, 0, expressao, rotulo))
    camada.setRenderer(QgsRuleBasedRenderer(raiz))


def definir_atual(id_carga: Optional[int]) -> None:
    """Marca a carga atual (variável do projeto) e redesenha Minhas cargas. Tira a seleção da camada: a seleção do
    QGIS pinta de amarelo por cima do contorno e ficaria para trás na carga já concluída."""
    QgsExpressionContextUtils.setProjectVariable(QgsProject.instance(), VAR_ATUAL, "" if id_carga is None else id_carga)
    for camada in camadas_minhas():
        camada.removeSelection()
        camada.triggerRepaint()


def carga_atual() -> Optional[int]:
    v = QgsExpressionContextUtils.projectScope(QgsProject.instance()).variable(VAR_ATUAL)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --- CQ: amostras e ocorrências (D3c) --------------------------------------------------------------------------------
VAR_AMOSTRA = "feixe_amostra_atual"  # a amostra atual (a carga de CQ), separada da carga atual da produção
_AMOSTRA_ATUAL = f'coalesce("id" = to_int(@{VAR_AMOSTRA}), false)'
PINO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icones", "pino.svg")
COR_OCORRENCIA = {"ocorrencias": "#FF3B30", "ocorrencias_ciencia": "#FF9F0A", "correcoes": "#FFD60A"}
NOME_CIENCIA, NOME_CORRECOES = "Ocorrências para ciência", "Correções a fazer"


def estilo_amostras(camada: QgsVectorLayer) -> None:
    """No espírito do executor (D-101), para avaliar sobre a imagem: a amostra atual só com o contorno magenta com
    halo; pendentes com hachura amarela espaçada; conformes com hachura verde densa; não conformes com hachura cruzada
    vermelha, que se vê de longe. O status vem da view juntada (texto no OGR: `to_int`)."""
    status = 'to_int("status")'
    regras = [
        ("Amostra atual", _AMOSTRA_ATUAL, _simbolo(_contorno("#FFFFFF", 2.0, 0.85), _contorno("#FF2BD6", 0.9)), True),
        (
            "Pendente", f'NOT {_AMOSTRA_ATUAL} AND "status" IS NULL',
            _simbolo(_hachura("#FFD23F", 45, 3.0, 0.35, 0.9), _contorno("#FFD23F", 0.5)), True,
        ),
        (
            "Conforme", f"NOT {_AMOSTRA_ATUAL} AND {status} = 1",
            _simbolo(_hachura("#3DDC6A", -45, 1.6, 0.4, 0.9), _contorno("#3DDC6A", 0.5)), True,
        ),
        (
            "Não conforme", f"NOT {_AMOSTRA_ATUAL} AND {status} = 0",
            _simbolo(
                _hachura("#FF5A4E", 45, 1.8, 0.4, 0.9), _hachura("#FF5A4E", -45, 1.8, 0.4, 0.9),
                _contorno("#FF5A4E", 0.6),
            ),
            True,
        ),
    ]  # fmt: skip
    camada.setRenderer(_regras(regras))


def estilo_ocorrencias(camada: QgsVectorLayer, papel_: str) -> None:
    """Pino (a ponta no ponto) com contorno branco e a anotação curta ao lado, com halo, para ler sobre a imagem. Cor
    por quem olha: vermelho para o avaliador, laranja para ciência, amarelo para a lista de correção."""
    from qgis.core import QgsMarkerSymbol, QgsMarkerSymbolLayer, QgsSvgMarkerSymbolLayer

    pino = QgsSvgMarkerSymbolLayer(PINO, 7.0, 0)
    pino.setFillColor(QColor(COR_OCORRENCIA.get(papel_, "#FF3B30")))
    pino.setStrokeColor(QColor("#FFFFFF"))
    pino.setStrokeWidth(0.4)
    pino.setVerticalAnchorPoint(QgsMarkerSymbolLayer.Bottom)
    simbolo = QgsMarkerSymbol()
    simbolo.changeSymbolLayer(0, pino)
    camada.setRenderer(QgsSingleSymbolRenderer(simbolo))
    rot = QgsPalLayerSettings()
    rot.isExpression = True
    rot.fieldName = (
        'CASE WHEN "anotacao" IS NULL OR trim("anotacao") = \'\' THEN "elemento" '
        'WHEN length("anotacao") > 28 THEN left("anotacao", 27) || \'…\' ELSE "anotacao" END'
    )
    fmt = QgsTextFormat()
    fmt.setSize(9)
    fmt.setColor(QColor("#1B1B1B"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1.2)
    buf.setColor(QColor("white"))
    fmt.setBuffer(buf)
    rot.setFormat(fmt)
    rot.dist = 1.5
    camada.setLabeling(QgsVectorLayerSimpleLabeling(rot))
    camada.setLabelsEnabled(True)


def definir_amostra_atual(id_carga: Optional[int]) -> None:
    """Marca a amostra atual (variável do projeto; o estilo de Amostras lê dela) e redesenha as camadas de amostras,
    sem a seleção (a seleção do QGIS pinta por cima do contorno)."""
    QgsExpressionContextUtils.setProjectVariable(
        QgsProject.instance(), VAR_AMOSTRA, "" if id_carga is None else id_carga
    )
    for camada in camadas_amostras():
        camada.removeSelection()
        camada.triggerRepaint()


def amostra_atual() -> Optional[int]:
    v = QgsExpressionContextUtils.projectScope(QgsProject.instance()).variable(VAR_AMOSTRA)
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


EXECUCAO, SUPERVISAO = "Execução", "Supervisão"
_PAPEL = "feixe/papel"  # propriedade da camada (e do subgrupo) que diz o que ela é, sem depender do nome
PAPEL_INFO = "minhas_cargas_info"  # a view juntada a Minhas cargas, no projeto e fora da árvore
PAPEL_INFO_AMOSTRA, PAPEL_INFO_OCORRENCIA = "amostras_info", "ocorrencias_info"  # as views juntadas do CQ
_INFOS = {
    PAPEL_INFO: (VW_CARGA_INFO, "Feixe · minhas cargas (folha e progresso)"),
    PAPEL_INFO_AMOSTRA: (VW_AMOSTRA_INFO, "Feixe · amostras (status e plano)"),
    PAPEL_INFO_OCORRENCIA: (VW_OCORRENCIA_INFO, "Feixe · ocorrências (folha e amostra)"),
}
MODOS = {"execucao": EXECUCAO, "supervisao": SUPERVISAO}  # modo de trabalho -> subgrupo do grupo Feixe


def _em(ids: List[int]) -> str:
    return ", ".join(str(int(i)) for i in ids) or "NULL"


def _folhas_do_grupo(uf: Optional[str], atividades: List[int]) -> str:
    """Lotes cuja etapa atual, aberta, é de uma atividade do subgrupo (com ou sem cargas geradas)."""
    sub = (
        "SELECT l.id FROM mapcartacomp.lote l JOIN mapcartacomp.lote_etapa le ON le.id_lote = l.id "
        "JOIN mapcartacomp.fluxo_etapa_atividade fa ON fa.id_fluxo_etapa = le.id_fluxo_etapa "
        f"WHERE le.situacao IN ('pendente', 'em_andamento') AND fa.id_atividade IN ({_em(atividades)})"
    )
    return " AND ".join(p for p in (_filtro_uf(uf), f"id_lote IN ({sub})") if p)


def _cargas_do_grupo(uf: Optional[str], atividades: List[int], responsavel: bool) -> str:
    quem = "responsavel IS NOT NULL" if responsavel else "responsavel IS NULL AND NOT concluido"
    return f"{_filtro_passagens(uf)} AND id_atividade IN ({_em(atividades)}) AND {quem}"


def _estilo_minhas_folhas(camada: QgsVectorLayer) -> None:
    """Moldura das folhas em que trabalho: contorno azul-escuro com halo claro e o rótulo MI-revisão, sem preencher."""
    camada.setRenderer(QgsSingleSymbolRenderer(_simbolo(_contorno("#FFFFFF", 1.4, 0.7), _contorno("#004182", 0.6))))
    rot = QgsPalLayerSettings()
    rot.fieldName = "folha_revisao"
    fmt = QgsTextFormat()
    fmt.setSize(12)
    fonte = fmt.font()
    fonte.setBold(True)
    fmt.setFont(fonte)
    fmt.setColor(QColor("#004182"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(1)
    buf.setColor(QColor("white"))
    fmt.setBuffer(buf)
    rot.setFormat(fmt)
    camada.setLabeling(QgsVectorLayerSimpleLabeling(rot))
    camada.setLabelsEnabled(True)


def _a_atribuir(camada: QgsVectorLayer) -> None:
    camada.setRenderer(
        QgsSingleSymbolRenderer(_simbolo(_hachura("#C88A00", 45, 2.5, 0.3, 0.8), _contorno("#C88A00", 0.3, 0.9)))
    )


def _preenchido(cor: QColor, opacidade: int = 120) -> QgsFillSymbol:
    return QgsFillSymbol.createSimple(
        {"color": f"{cor.red()},{cor.green()},{cor.blue()},{opacidade}", "outline_color": cor.darker(160).name(),
         "outline_width": "0.3"}
    )  # fmt: skip


def _regras(regras: List[tuple]) -> QgsRuleBasedRenderer:
    """(rótulo, expressão, símbolo, ligada) -> estilo por regras; regra desligada = desmarcada na legenda."""
    raiz = QgsRuleBasedRenderer.Rule(None)
    for rotulo, expressao, simbolo, ligada in regras:
        r = QgsRuleBasedRenderer.Rule(simbolo, 0, 0, expressao, rotulo)
        r.setActive(ligada)
        raiz.appendChild(r)
    return QgsRuleBasedRenderer(raiz)


CONCLUIDAS = "Concluídas"
ESTILO_RESPONSAVEL, ESTILO_SITUACAO = "Por responsável", "Por situação"


def estilos_cargas(camada: QgsVectorLayer, pessoas: List[Dict], cores: Dict[str, QColor]) -> None:
    """Dois estilos na mesma camada (menu Estilos do QGIS): por responsável (padrão) e por situação. Nos dois, as
    concluídas ficam desmarcadas na legenda: a camada mostra o que está pendente, e quem quiser liga as concluídas."""
    concluida = QgsFillSymbol.createSimple({"color": "160,160,160,70", "outline_color": "110,110,110,160"})
    por_resp = [
        (f"{p['nome']} ({p['pendentes']})", f"NOT \"concluido\" AND \"responsavel\" = '{p['conta']}'",
         _preenchido(cores[p["conta"]]), True)
        for p in pessoas
    ]  # fmt: skip
    contas = ", ".join(f"'{p['conta']}'" for p in pessoas) or "''"
    por_resp.append(
        ("Outros (carregue as camadas de novo)", f"NOT \"concluido\" AND \"responsavel\" NOT IN ({contas})",
         _preenchido(QColor(150, 150, 150), 90), True)
    )  # fmt: skip
    por_resp.append((CONCLUIDAS, '"concluido"', concluida, False))
    pendente = _preenchido(QColor("#2E7BD6"), 110)
    por_situacao = [
        ("Pendentes", 'NOT "concluido"', pendente, True),
        (CONCLUIDAS, '"concluido"', concluida.clone(), False),
    ]
    gerente = camada.styleManager()
    camada.setRenderer(_regras(por_situacao))
    gerente.renameStyle(gerente.currentStyle(), ESTILO_SITUACAO)
    gerente.addStyleFromLayer(ESTILO_RESPONSAVEL)
    gerente.setCurrentStyle(ESTILO_RESPONSAVEL)
    camada.setRenderer(_regras(por_resp))
    gerente.addStyleFromLayer(ESTILO_RESPONSAVEL)


def montar(
    amb: Ambiente,
    authcfg: str,
    eu: Dict,
    responsaveis: List[Dict],
    grupos_supervisao: Optional[List[Dict]],
    grupos_execucao: List[Dict],
    gpkg: str,
) -> Dict:
    """(Re)monta o grupo Feixe no topo do projeto, por tarefa (D-101) e por atividade em produção (D-102).

    - Execução, do workspace `gpkg` (C4): Minhas cargas e Minhas folhas, só das passagens abertas; com mais de uma
      atividade, um subgrupo por atividade. Funciona sem a CCAR.
    - Supervisão (só supervisor), da CCAR: um subgrupo por atividade em produção na UF (as de CQ de um tema juntas),
      cada um com Folhas, Cargas por responsável (concluídas desmarcadas; estilo alternativo por situação) e Cargas a
      atribuir. Só o subgrupo com mais folhas vem ligado. `grupos_supervisao` None = a CCAR não respondeu: o grupo
      vem sem a Supervisão.

    `grupos_*` vêm de `dados.grupos` (a execução, de `dados.local.grupos`); `responsaveis` de
    `dados.grupos.responsaveis` (por atividade). O modo inicial é o do papel. Devolve o modo, os subgrupos e o nome e
    a contagem de feições de cada camada.
    """
    from . import formularios

    uf = eu.get("uf")
    supervisor = "supervisor" in (eu.get("papeis") or []) and grupos_supervisao is not None
    if supervisor and not authcfg:
        raise RuntimeError("usuário e senha ainda não configurados")
    projeto = QgsProject.instance()
    raiz = projeto.layerTreeRoot()
    antigo = raiz.findGroup(GRUPO)
    if antigo is not None:
        projeto.removeMapLayers([c.layerId() for c in antigo.findLayers()])
        raiz.removeChildNode(antigo)
    projeto.removeMapLayers([c.id() for c in _auxiliares()])
    grupo: QgsLayerTreeGroup = raiz.insertGroup(0, GRUPO)
    carregadas = []

    def por(sub, camada, papel, visivel=True):
        camada.setCustomProperty(_PAPEL, papel)
        projeto.addMapLayer(camada, False)
        sub.addLayer(camada).setItemVisibilityChecked(visivel)
        carregadas.append(camada)

    # As views juntadas (folha e progresso de Minhas cargas; status e plano das amostras; folha e amostra das
    # ocorrências): no projeto (para a junção sobreviver a salvar e abrir o projeto), fora da árvore, e só as usadas.
    infos = _Infos(gpkg)

    execucao = grupo.addGroup(EXECUCAO)
    ciencia = camada_ciencia_nova(gpkg, infos)
    if ciencia is not None:
        por(execucao, ciencia, "ocorrencias_ciencia")
    for spec in lgrupos.plano_execucao(grupos_execucao or []):
        sub = execucao if spec["rotulo"] is None else execucao.addGroup(spec["rotulo"])
        atividades = spec["atividades"]
        if spec["tipo"] == "cq":
            sub.setCustomProperty(_PAPEL, "cq")
            for e in spec["elementos"]:
                oc = _camada_ocorrencias(gpkg, infos, f"Ocorrências - {e['elemento']}", "ocorrencias",
                                         lgrupos.filtro_ocorrencias(e["id_atividade"]))  # fmt: skip
                por(sub, oc, "ocorrencias", e["visivel"])
                am = _camada_gpkg(gpkg, "carga_trabalho", f"Amostras - {e['elemento']}",
                                  lgrupos.filtro_amostras(e["id_atividade"]))  # fmt: skip
                _juntar_info(am, infos.de(PAPEL_INFO_AMOSTRA))
                estilo_amostras(am)
                formularios.amostras(am)
                _esconder_colunas(am)
                am.setReadOnly(True)  # a avaliação vai pelas ações (camada e barra), nunca pelo buffer do QGIS
                por(sub, am, "amostras", e["visivel"])
            folhas = _camada_gpkg(gpkg, VW_MINHAS_FOLHAS, "Minhas folhas", _filtro_minhas_folhas(atividades))
            _estilo_minhas_folhas(folhas)
            formularios.folhas_cq(folhas)
            por(sub, folhas, "minhas_folhas")
            continue
        if spec["correcoes"]:
            corr = _camada_ocorrencias(gpkg, infos, NOME_CORRECOES, "correcoes",
                                       lgrupos.filtro_correcoes(atividades))  # fmt: skip
            por(sub, corr, "correcoes", _contar(corr) > 0)
        minhas = _camada_gpkg(gpkg, "carga_trabalho", "Minhas cargas", _filtro_minhas(atividades))
        _juntar_info(minhas, infos.de(PAPEL_INFO))
        estilo_minhas(minhas)
        formularios.minhas_cargas(minhas)
        _esconder_colunas(minhas)
        por(sub, minhas, "minhas_cargas")
        folhas = _camada_gpkg(gpkg, VW_MINHAS_FOLHAS, "Minhas folhas", _filtro_minhas_folhas(atividades))
        _estilo_minhas_folhas(folhas)
        formularios.minhas_folhas(folhas, minhas.id())
        por(sub, folhas, "minhas_folhas")

    if supervisor:
        sup = grupo.addGroup(SUPERVISAO)
        contas = sorted({r["conta"] for r in responsaveis})
        cores = dict(zip(contas, cores_distintas(len(contas))))
        ligado = None
        for g in grupos_supervisao:
            sub = sup.addGroup(g["rotulo"])
            sub.setCustomProperty(_PAPEL, g["chave"])
            pessoas: Dict[str, Dict] = {}
            for r in responsaveis:
                if r["id_atividade"] in g["atividades"]:
                    p = pessoas.setdefault(r["conta"], {"conta": r["conta"], "nome": r["nome"], "pendentes": 0})
                    p["pendentes"] += r["pendentes"]
            f = _camada(amb, authcfg, "Folhas", "ctrl_lote", "id_lote", _folhas_do_grupo(uf, g["atividades"]),
                        "folhas.qml")  # fmt: skip
            formularios.folhas_supervisao(f)
            por(sub, f, "folhas")
            resp = _camada(amb, authcfg, "Cargas por responsável", "vw_carga_supervisao", "id",
                           _cargas_do_grupo(uf, g["atividades"], True))  # fmt: skip
            estilos_cargas(resp, sorted(pessoas.values(), key=lambda p: p["nome"]), cores)
            formularios.cargas_supervisao(resp)
            por(sub, resp, "cargas_responsavel")
            livres = _camada(amb, authcfg, "Cargas a atribuir", "vw_carga_supervisao", "id",
                             _cargas_do_grupo(uf, g["atividades"], False))  # fmt: skip
            _a_atribuir(livres)
            formularios.cargas_supervisao(livres)
            por(sub, livres, "cargas_a_atribuir")
            n = f.featureCount()
            if ligado is None or n > ligado[1]:
                ligado = (sub, n)
        for sub in sup.children():
            visivel = ligado is not None and sub is ligado[0]
            sub.setItemVisibilityChecked(visivel)
            sub.setExpanded(visivel)
    escolhido = modo("supervisao" if supervisor else "execucao")
    return {
        "modo": escolhido,
        "grupos": {"execucao": [g["rotulo"] for g in grupos_execucao],
                   "supervisao": [g["rotulo"] for g in grupos_supervisao] if supervisor else []},
        "camadas": [{"nome": c.name(), "feicoes": _contar(c)} for c in carregadas],
    }  # fmt: skip


def _auxiliares() -> List[QgsVectorLayer]:
    """Camadas do Feixe fora da árvore (as views juntadas)."""
    return [c for c in QgsProject.instance().mapLayers().values() if c.customProperty(_PAPEL) in _INFOS]


class _Infos:
    """As views juntadas de uma montagem, criadas na primeira vez que uma camada pede (ou reaproveitadas do projeto,
    quando a camada nasce depois da montagem: ocorrências para ciência que chegaram pela sincronização)."""

    def __init__(self, gpkg: str):
        self.gpkg = gpkg
        self._camadas: Dict[str, QgsVectorLayer] = {}

    def de(self, papel_: str) -> QgsVectorLayer:
        if papel_ not in self._camadas:
            existente = next((c for c in _auxiliares() if c.customProperty(_PAPEL) == papel_), None)
            if existente is not None:
                self._camadas[papel_] = existente
            else:
                vw, nome = _INFOS[papel_]
                info = _camada_gpkg(self.gpkg, vw, nome)
                info.setCustomProperty(_PAPEL, papel_)
                QgsProject.instance().addMapLayer(info, False)
                self._camadas[papel_] = info
        return self._camadas[papel_]


def _camada_ocorrencias(gpkg: str, infos: _Infos, nome: str, papel_: str, filtro: str) -> QgsVectorLayer:
    from . import formularios

    camada = _camada_gpkg(gpkg, "cq_inspecao", nome, filtro)
    _juntar_info(camada, infos.de(PAPEL_INFO_OCORRENCIA), "uuid")
    estilo_ocorrencias(camada, papel_)
    formularios.ocorrencias(camada, papel_)
    _esconder_colunas(camada)
    if papel_ != "ocorrencias":
        camada.setReadOnly(True)  # ciência e correção são só leitura; o Ciente é ação (camada e barra)
    return camada


def camada_ciencia_nova(gpkg: str, infos: Optional[_Infos] = None) -> Optional[QgsVectorLayer]:
    """Ocorrências para ciência, só se houver alguma (o APM que nunca recebeu ocorrência não ganha camada vazia)."""
    teste = _camada_gpkg(gpkg, "cq_inspecao", NOME_CIENCIA, lgrupos.FILTRO_CIENCIA)
    if _contar(teste) == 0:
        return None
    return _camada_ocorrencias(gpkg, infos or _Infos(gpkg), NOME_CIENCIA, "ocorrencias_ciencia",
                               lgrupos.FILTRO_CIENCIA)  # fmt: skip


def garantir_ciencia() -> bool:
    """Depois de uma sincronização: se chegaram ocorrências para a minha ciência e a camada não existe (não havia
    nenhuma ao montar), ela entra no topo da Execução, ligada. Volta True se criou."""
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    execucao = grupo.findGroup(EXECUCAO) if grupo is not None else None
    if execucao is None or camada_ciencia() is not None:
        return False
    gpkg = _gpkg_do_grupo()
    if gpkg is None:
        return False
    camada = camada_ciencia_nova(gpkg)
    if camada is None:
        return False
    camada.setCustomProperty(_PAPEL, "ocorrencias_ciencia")
    QgsProject.instance().addMapLayer(camada, False)
    execucao.insertLayer(0, camada).setItemVisibilityChecked(True)
    return True


def ligar(camada) -> None:
    """Liga a camada na árvore (a de ciência, quando chegam ocorrências)."""
    if camada is None:
        return
    no = QgsProject.instance().layerTreeRoot().findLayer(camada.id())
    if no is not None:
        no.setItemVisibilityChecked(True)


def _gpkg_do_grupo() -> Optional[str]:
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    for no in grupo.findLayers() if grupo is not None else []:
        if do_workspace(no.layer()):
            return no.layer().source().split("|")[0]
    return None


def modo_atual() -> Optional[str]:
    """Modo ligado agora (execucao ou supervisao), pela visibilidade dos subgrupos; None sem o grupo Feixe."""
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    if grupo is None:
        return None
    for chave, nome in MODOS.items():
        sub = grupo.findGroup(nome)
        if sub is not None and sub.itemVisibilityChecked():
            return chave
    return None


def modo(chave: str) -> str:
    """Liga o subgrupo do modo e desliga (e recolhe) o outro. Só visibilidade: nada é recarregado do banco."""
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    if grupo is None:
        raise RuntimeError("carregue as camadas do Feixe primeiro")
    if grupo.findGroup(MODOS[chave]) is None:
        raise RuntimeError("o modo supervisão é só para supervisor")
    for outra, nome in MODOS.items():
        sub = grupo.findGroup(nome)
        if sub is not None:
            sub.setItemVisibilityChecked(outra == chave)
            sub.setExpanded(outra == chave)
    return chave


# --- Minhas cargas: seleção e recarga (B2) ----------------------------------------------------------------------------


def camadas_minhas() -> List[QgsVectorLayer]:
    """As camadas Minhas cargas do grupo Feixe (uma por atividade, quando a pessoa tem mais de uma)."""
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    if grupo is None:
        return []
    return [
        n.layer() for n in grupo.findLayers()
        if n.layer() is not None and n.layer().customProperty(_PAPEL) == "minhas_cargas"
    ]  # fmt: skip


def camada_minhas() -> Optional[QgsVectorLayer]:
    camadas = camadas_minhas()
    return camadas[0] if camadas else None


def camadas_do_papel(*papeis: str) -> List[QgsVectorLayer]:
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    if grupo is None:
        return []
    return [n.layer() for n in grupo.findLayers() if n.layer() is not None and papel(n.layer()) in papeis]


def camadas_amostras() -> List[QgsVectorLayer]:
    return camadas_do_papel("amostras")


def camada_ciencia() -> Optional[QgsVectorLayer]:
    camadas = camadas_do_papel("ocorrencias_ciencia")
    return camadas[0] if camadas else None


def camada_com_amostra(id_carga: int) -> Optional[QgsVectorLayer]:
    for camada in camadas_amostras():
        if next(camada.getFeatures(f'"id" = {int(id_carga)}'), None) is not None:
            return camada
    return None


def amostra_selecionada() -> Optional[int]:
    """Id da carga de CQ da primeira amostra selecionada (a escolha à mão vale mais que a atual)."""
    for camada in camadas_amostras():
        for f in camada.getSelectedFeatures():
            return int(f["id"])
    return None


def amostra_no_ponto(x: float, y: float) -> Optional[int]:
    """A amostra minha (carga de CQ de passagem aberta) que contém o ponto, em SIRGAS 2000 geográfico: a atual, se o
    ponto cai nela; senão a que estiver sob o clique. Fora de todas: None."""
    from qgis.core import QgsGeometry, QgsPointXY, QgsRectangle

    ponto = QgsGeometry.fromPointXY(QgsPointXY(x, y))
    pedido = QgsFeatureRequest().setFilterRect(QgsRectangle(x, y, x, y))
    achadas = []
    for camada in camadas_amostras():
        for f in camada.getFeatures(pedido):
            if f.hasGeometry() and f.geometry().intersects(ponto):
                achadas.append(int(f["id"]))
    atual = amostra_atual()
    if atual in achadas:
        return atual
    return achadas[0] if achadas else None


def ocorrencia_selecionada(*papeis: str) -> Optional[str]:
    """Uuid da primeira ocorrência selecionada nas camadas dos papéis (a ciência: Ocorrências para ciência)."""
    for camada in camadas_do_papel(*(papeis or ("ocorrencias_ciencia",))):
        for f in camada.getSelectedFeatures():
            return str(f["uuid"])
    return None


def camada_com_carga(id_carga: int) -> Optional[QgsVectorLayer]:
    for camada in camadas_minhas():
        if next(camada.getFeatures(f'"id" = {int(id_carga)}'), None) is not None:
            return camada
    return None


def carga_selecionada() -> Optional[int]:
    """Id da primeira carga selecionada em Minhas cargas, ou None (a escolha à mão vale mais que a atual)."""
    for camada in camadas_minhas():
        for f in camada.getSelectedFeatures():
            return int(f["id"])
    return None


def recarregar_cargas(so_workspace: bool = False) -> None:
    """As camadas do grupo Feixe releem a origem: depois de uma escrita da execução (`so_workspace`: só as do
    workspace, que mostram na hora; as da CCAR esperam o push) ou de uma sincronização que mudou algo (todas). Camada
    em edição fica como está, para não atrapalhar quem edita; ela recarrega quando a edição termina."""
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    if grupo is None:
        return
    renovadas: set = set()
    for no in grupo.findLayers():
        camada = no.layer()
        if not isinstance(camada, QgsVectorLayer) or camada.isEditable():
            continue
        if so_workspace and not do_workspace(camada):
            continue
        _renovar_juncoes(camada, renovadas)
        camada.dataProvider().reloadData()
        camada.triggerRepaint()


def _renovar_juncoes(camada: QgsVectorLayer, renovadas: set) -> None:
    """A junção em memória não vê a view mudar: relê a view (uma vez por recarga) e refaz a junção com uma
    `QgsVectorLayerJoinInfo` nova. Devolver a cópia de `vectorJoins()` não serve: ela leva o cache antigo marcado como
    limpo, e o QGIS não relê a view (os valores juntados ficavam os da montagem)."""
    for j in camada.vectorJoins():
        info = j.joinLayer()
        if info is None:
            continue
        if info.id() not in renovadas:
            info.dataProvider().reloadData()
            renovadas.add(info.id())
        camada.removeJoin(j.joinLayerId())
        _juntar_info(camada, info, j.targetFieldName())


def cargas_selecionadas() -> Dict:
    """Ids das cargas selecionadas nas camadas de cargas do grupo Feixe."""
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    ids, camadas_ = set(), []
    for no in grupo.findLayers() if grupo else []:
        camada = no.layer()
        if not isinstance(camada, QgsVectorLayer) or not camada.selectedFeatureCount():
            continue
        papel = camada.customProperty(_PAPEL)
        if papel not in ("minhas_cargas", "cargas_responsavel", "cargas_a_atribuir"):
            continue  # não é camada de cargas (Folhas, Minhas folhas)
        ids.update(int(f["id"]) for f in camada.getSelectedFeatures())
        camadas_.append(camada.name())
    return {"ids": sorted(ids), "camadas": camadas_}


# --- Malha de folhas para escolher no mapa (Novas folhas) ---------------------------------------------------------

NOME_MALHA = "Folhas 1:100.000 · escolher"
ESCOLHIDA, NO_FEIXE, LIVRE = "escolhida", "no_feixe", "livre"


def camada_malha() -> Optional[QgsVectorLayer]:
    for camada in QgsProject.instance().mapLayersByName(NOME_MALHA):
        if camada.customProperty(_PAPEL) == "malha_folhas":
            return camada
    return None


def remover_malha() -> None:
    camada = camada_malha()
    if camada is not None:
        QgsProject.instance().removeMapLayer(camada.id())


def _valor(v):
    """Atributo de feição como valor Python: no QGIS 3.22 a 3.28, atributo nulo volta como QVariant nulo, que não vira
    JSON nem compara com None."""
    from qgis.PyQt.QtCore import QVariant

    if isinstance(v, QVariant):
        return None if v.isNull() else v.value()
    return v


def _estado(id_folha: int, no_feixe: Dict[int, str], escolhidas: set) -> str:
    if id_folha in escolhidas:
        return ESCOLHIDA
    return NO_FEIXE if id_folha in no_feixe else LIVRE


def _estilo_malha(camada: QgsVectorLayer) -> None:
    camada.setRenderer(
        _regras(
            [
                (
                    "Escolhidas agora",
                    f"\"estado\" = '{ESCOLHIDA}'",
                    QgsFillSymbol.createSimple(
                        {"color": "19,81,180,110", "outline_color": "#0C326F", "outline_width": "0.6"}
                    ),
                    True,
                ),
                (
                    "Já no Feixe",
                    f"\"estado\" = '{NO_FEIXE}'",
                    _simbolo(_hachura("#5C6B7A", 45, 1.6, 0.25, 0.7), _contorno("#5C6B7A", 0.4)),
                    True,
                ),
                ("Livres", f"\"estado\" = '{LIVRE}'", _simbolo(_contorno("#8A96A3", 0.25, 0.9)), True),
            ]
        )  # fmt: skip
    )
    rot = QgsPalLayerSettings()
    rot.isExpression = True
    rot.fieldName = '"cd_mi" || if("rotulo" IS NOT NULL, \'\\n\' || "rotulo", \'\')'
    rot.scaleVisibility = True
    rot.maximumScale, rot.minimumScale = 1, 4_000_000  # o país inteiro com 3 mil rótulos não se lê
    fmt = QgsTextFormat()
    fmt.setSize(9)
    fmt.setColor(QColor("#1B2733"))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(0.8)
    buf.setColor(QColor("white"))
    fmt.setBuffer(buf)
    rot.setFormat(fmt)
    camada.setLabeling(QgsVectorLayerSimpleLabeling(rot))
    camada.setLabelsEnabled(True)


def mostrar_malha(folhas: List[Dict], no_feixe: Dict[int, str], escolhidas: List[int]) -> QgsVectorLayer:
    """Camada temporária (memória) no topo do projeto com a malha de folhas 1:100.000 e o estado de cada uma:
    escolhida agora (no painel), já no Feixe (o rótulo diz onde ou em que temas) ou livre. Substitui a anterior."""
    from qgis.core import QgsFeature, QgsField, QgsGeometry
    from qgis.PyQt.QtCore import QVariant

    remover_malha()
    camada = QgsVectorLayer("Polygon?crs=EPSG:4674", NOME_MALHA, "memory")
    camada.dataProvider().addAttributes([
        QgsField("id", QVariant.Int), QgsField("cd_mi", QVariant.String), QgsField("nm_carta", QVariant.String),
        QgsField("nomenclatura", QVariant.String), QgsField("estado", QVariant.String),
        QgsField("rotulo", QVariant.String),
    ])  # fmt: skip
    camada.updateFields()
    marcadas, feicoes = set(escolhidas), []
    for f in folhas:
        feicao = QgsFeature(camada.fields())
        feicao.setGeometry(QgsGeometry.fromWkt(f["wkt"]))
        feicao.setAttributes([
            f["id"], f["cd_mi"], f.get("nm_carta"), f.get("nomenclatura"), _estado(f["id"], no_feixe, marcadas),
            no_feixe.get(f["id"]),
        ])  # fmt: skip
        feicoes.append(feicao)
    camada.dataProvider().addFeatures(feicoes)
    camada.updateExtents()
    camada.setCustomProperty(_PAPEL, "malha_folhas")
    _estilo_malha(camada)
    QgsProject.instance().addMapLayer(camada, False)
    QgsProject.instance().layerTreeRoot().insertLayer(0, camada)
    return camada


def marcar_malha(no_feixe: Dict[int, str], escolhidas: List[int]) -> None:
    """Atualiza o estado das folhas da malha (o painel mudou a lista, ou o fluxo, que muda o que já está no Feixe)."""
    camada = camada_malha()
    if camada is None:
        return
    marcadas = set(escolhidas)
    i_estado, i_rotulo = camada.fields().indexOf("estado"), camada.fields().indexOf("rotulo")
    mudancas = {}
    for f in camada.getFeatures():
        novo = {i_estado: _estado(f["id"], no_feixe, marcadas), i_rotulo: no_feixe.get(f["id"])}
        if _valor(f["estado"]) != novo[i_estado] or _valor(f["rotulo"]) != novo[i_rotulo]:
            mudancas[f.id()] = novo
    if mudancas:
        camada.dataProvider().changeAttributeValues(mudancas)
        camada.triggerRepaint()


def folhas_da_malha(geometria, so_cobertas: bool = False) -> List[Dict]:
    """Folhas da malha que tocam a geometria (ponto ou retângulo, já no SIRGAS 2000 geográfico). `so_cobertas`: só as
    que a geometria cobre em parte de fato; encostar na borda de uma folha vizinha não conta."""
    from qgis.core import QgsFeatureRequest

    camada = camada_malha()
    if camada is None:
        return []
    pedido = QgsFeatureRequest().setFilterRect(geometria.boundingBox())
    return [
        {k: _valor(f[k]) for k in ("id", "cd_mi", "nm_carta", "estado", "rotulo")}
        for f in camada.getFeatures(pedido)
        if f.geometry().intersects(geometria)
        and (not so_cobertas or f.geometry().intersection(geometria).area() > 1e-9)
    ]
