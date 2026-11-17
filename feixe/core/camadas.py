"""Camadas do Feixe no projeto aberto do QGIS: o grupo "Feixe", organizado por tarefa (D-101).

Na fase B as camadas leem direto do banco da CCAR, com a mesma credencial do Authentication Manager (authcfg); na fase
C passam a ler do workspace local. Roda na thread principal (mexe no projeto e na árvore de camadas).

Dois subgrupos, um por modo de trabalho; só um fica ligado (a barra troca o modo, sem recarregar):

Execução (todos):
- Minhas cargas: `vw_carga_trabalho` (cargas da conta conectada, current_user, só de passagens abertas), feita para
  ficar ligada o dia todo
  sobre a imagem (D-101): a carga atual (a da barra: próxima, concluir, zoom do painel) só com contorno duplo
  magenta com halo branco, para ver a imagem inteira dentro dela; pendentes com hachura espaçada azul-clara;
  concluídas há até 3 dias com hachura verde mais densa; concluídas antes, hachura cruzada cinza-clara. Cores claras
  e saturadas porque a imagem por baixo é escura (vegetação, solo, água). Só `concluido` é editável: concluir pela
  tabela de atributos grava no banco, e as regras preenchem `concluido_em`.
- Minhas folhas: moldura e rótulo das folhas em que a pessoa tem cargas de passagens abertas.

Supervisão (só supervisor), das passagens abertas dos lotes da UF:
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
    QgsVectorLayerSimpleLabeling,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from .ambiente import Ambiente
from .dados.cargas import SQL_PASSAGENS_ATUAIS

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


def _so_concluido_editavel(camada: QgsVectorLayer) -> None:
    cfg = camada.editFormConfig()
    for i, campo in enumerate(camada.fields()):
        cfg.setReadOnly(i, campo.name() != "concluido")
    camada.setEditFormConfig(cfg)


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
_ATUAL = f'coalesce("id_carga_trabalho" = to_int(@{VAR_ATUAL}), false)'


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


EXECUCAO, SUPERVISAO = "Execução", "Supervisão"
_PAPEL = "feixe/papel"  # propriedade da camada (e do subgrupo) que diz o que ela é, sem depender do nome
MODOS = {"execucao": EXECUCAO, "supervisao": SUPERVISAO}  # modo de trabalho -> subgrupo do grupo Feixe


def _em(ids: List[int]) -> str:
    return ", ".join(str(int(i)) for i in ids) or "NULL"


def _so_minhas_abertas(atividades: Optional[List[int]] = None) -> str:
    """Cargas minhas de passagens abertas (e das atividades do subgrupo): o encerrado sai do mapa de quem executa."""
    extra = f" AND c.id_atividade IN ({_em(atividades)})" if atividades else ""
    return (
        "id_carga_trabalho IN (SELECT c.id FROM mapcartacomp.carga_trabalho c WHERE c.responsavel = current_user "
        f"AND c.id_lote_etapa IN ({SQL_PASSAGENS_ATUAIS}){extra})"
    )


def _so_minhas_folhas(atividades: Optional[List[int]] = None) -> str:
    extra = f" AND c.id_atividade IN ({_em(atividades)})" if atividades else ""
    return (
        "id_lote IN (SELECT le.id_lote FROM mapcartacomp.carga_trabalho c JOIN mapcartacomp.lote_etapa le "
        f"ON le.id = c.id_lote_etapa WHERE c.responsavel = current_user AND le.id IN ({SQL_PASSAGENS_ATUAIS}){extra})"
    )


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
    grupos_supervisao: List[Dict],
    grupos_execucao: List[Dict],
) -> Dict:
    """(Re)monta o grupo Feixe no topo do projeto, por tarefa (D-101) e por atividade em produção (D-102).

    - Execução: Minhas cargas e Minhas folhas, só das passagens abertas; com mais de uma atividade, um subgrupo por
      atividade.
    - Supervisão (só supervisor): um subgrupo por atividade em produção na UF (as de CQ de um tema juntas), cada um
      com Folhas, Cargas por responsável (concluídas desmarcadas; estilo alternativo por situação) e Cargas a
      atribuir. Só o subgrupo com mais folhas vem ligado.

    `grupos_*` vêm de `dados.grupos`; `responsaveis` de `dados.grupos.responsaveis` (por atividade). O modo inicial é
    o do papel. Devolve o modo, os subgrupos e o nome e a contagem de feições de cada camada.
    """
    from . import formularios

    if not authcfg:
        raise RuntimeError("usuário e senha ainda não configurados")
    uf = eu.get("uf")
    supervisor = "supervisor" in (eu.get("papeis") or [])
    projeto = QgsProject.instance()
    raiz = projeto.layerTreeRoot()
    antigo = raiz.findGroup(GRUPO)
    if antigo is not None:
        projeto.removeMapLayers([c.layerId() for c in antigo.findLayers()])
        raiz.removeChildNode(antigo)
    grupo: QgsLayerTreeGroup = raiz.insertGroup(0, GRUPO)
    carregadas = []

    def por(sub, camada, papel, visivel=True):
        camada.setCustomProperty(_PAPEL, papel)
        projeto.addMapLayer(camada, False)
        sub.addLayer(camada).setItemVisibilityChecked(visivel)
        carregadas.append(camada)

    execucao = grupo.addGroup(EXECUCAO)
    for g in grupos_execucao or [None]:
        sub = execucao if len(grupos_execucao) <= 1 else execucao.addGroup(g["rotulo"])
        atividades = g["atividades"] if g and len(grupos_execucao) > 1 else None
        minhas = _camada(
            amb, authcfg, "Minhas cargas", "vw_carga_trabalho", "id_carga_trabalho", _so_minhas_abertas(atividades)
        )
        estilo_minhas(minhas)
        _so_concluido_editavel(minhas)
        formularios.minhas_cargas(minhas)
        por(sub, minhas, "minhas_cargas")
        folhas = _camada(amb, authcfg, "Minhas folhas", "ctrl_lote", "id_lote", _so_minhas_folhas(atividades))
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
        "camadas": [{"nome": c.name(), "feicoes": c.featureCount()} for c in carregadas],
    }  # fmt: skip


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


def camada_com_carga(id_carga: int) -> Optional[QgsVectorLayer]:
    for camada in camadas_minhas():
        if next(camada.getFeatures(f'"id_carga_trabalho" = {int(id_carga)}'), None) is not None:
            return camada
    return None


def carga_selecionada() -> Optional[int]:
    """Id da primeira carga selecionada em Minhas cargas, ou None (a escolha à mão vale mais que a atual)."""
    for camada in camadas_minhas():
        for f in camada.getSelectedFeatures():
            return int(f["id_carga_trabalho"])
    return None


def recarregar_cargas() -> None:
    """As camadas do grupo Feixe releem o banco (depois de concluir ou desfazer por fora da tabela de atributos)."""
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    if grupo is None:
        return
    for no in grupo.findLayers():
        camada = no.layer()
        if camada is not None and not camada.isEditable():
            camada.dataProvider().reloadData()
            camada.triggerRepaint()


# --- Prévia das cargas geradas pela grade (B4) ------------------------------------------------------------------------
NOME_PREVIA = "Prévia de cargas"


def remover_previa() -> None:
    projeto = QgsProject.instance()
    projeto.removeMapLayers([c.id() for c in projeto.mapLayersByName(NOME_PREVIA)])


def mostrar_previa(celulas: List[Dict]) -> QgsVectorLayer:
    """Camada temporária (memória) com as células que seriam gravadas, no topo do projeto. Substitui a anterior."""
    from qgis.core import QgsFeature, QgsField, QgsGeometry
    from qgis.PyQt.QtCore import QVariant

    remover_previa()
    camada = QgsVectorLayer("MultiPolygon?crs=EPSG:4674", NOME_PREVIA, "memory")
    camada.dataProvider().addAttributes([QgsField("geocodigo", QVariant.String), QgsField("folha", QVariant.String)])
    camada.updateFields()
    feicoes = []
    for c in celulas:
        f = QgsFeature(camada.fields())
        f.setGeometry(QgsGeometry.fromWkt(c["wkt"]))
        f.setAttributes([c["geocodigo"], c.get("folha")])
        feicoes.append(f)
    camada.dataProvider().addFeatures(feicoes)
    camada.updateExtents()
    camada.setRenderer(
        QgsSingleSymbolRenderer(
            QgsFillSymbol.createSimple(
                {"color": "255,0,0,30", "outline_color": "220,30,30,255", "outline_width": "0.5"}
            )
        )
    )
    QgsProject.instance().addMapLayer(camada, False)
    QgsProject.instance().layerTreeRoot().insertLayer(0, camada)
    return camada


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
            continue  # não é camada de cargas (Folhas, Minhas folhas, prévia)
        campo = "id_carga_trabalho" if papel == "minhas_cargas" else "id"
        ids.update(int(f[campo]) for f in camada.getSelectedFeatures())
        camadas_.append(camada.name())
    return {"ids": sorted(ids), "camadas": camadas_}
