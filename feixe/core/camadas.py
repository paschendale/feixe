"""Camadas do Feixe no projeto aberto do QGIS: o grupo "Feixe" com as cargas e as folhas.

Na fase B as camadas leem direto do banco da CCAR, com a mesma credencial do Authentication Manager (authcfg); na fase
C passam a ler do workspace local. Roda na thread principal (mexe no projeto e na árvore de camadas).

- Minhas cargas: `vw_carga_trabalho` (cargas da conta conectada, current_user), com o estilo do projeto "Aquisição de
  ADE" do DF (concluída há menos de 3 dias, há mais de 3 dias, pendente). Só `concluido` é editável: concluir pela
  tabela de atributos grava no banco, e as regras preenchem `concluido_em`.
- Folhas: subgrupo com uma camada por tema ("Folhas · Hidrografia"...), de `ctrl_lote` da UF, rotulada
  "MI-revisão · responsável · etapa", com o estilo da articulação do DF. A mesma folha tem um lote por tema; numa
  camada só, os rótulos dos temas se sobrepunham. Só o tema com mais folhas fica ligado.
- Só para supervisor: Cargas por responsável (uma cor por pessoa) e Cargas disponíveis (responsável nulo), das
  passagens atuais dos lotes da UF.
"""

from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsDataSourceUri,
    QgsFillSymbol,
    QgsLayerTreeGroup,
    QgsLimitedRandomColorRamp,
    QgsProject,
    QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
    QgsWkbTypes,
)

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


def _por_responsavel(camada: QgsVectorLayer, responsaveis: List[Dict]) -> None:
    rampa = QgsLimitedRandomColorRamp(max(len(responsaveis), 1), 60, 200, 120, 240, 0, 359)
    categorias = []
    for i, r in enumerate(responsaveis):
        cor = rampa.color(i / max(len(responsaveis) - 1, 1))
        simbolo = QgsFillSymbol.createSimple(
            {"color": f"{cor.red()},{cor.green()},{cor.blue()},110", "outline_color": "50,50,50,200"}
        )
        categorias.append(QgsRendererCategory(r["conta"], simbolo, f"{r['nome']} ({r['cargas']})"))
    # Valor vazio = "todos os outros": quem recebeu cargas depois de montar aparece em cinza até remontar.
    outros = QgsFillSymbol.createSimple({"color": "150,150,150,90", "outline_color": "80,80,80,200"})
    categorias.append(QgsRendererCategory("", outros, "Outros (remonte as camadas)"))
    camada.setRenderer(QgsCategorizedSymbolRenderer("responsavel", categorias))


MODULOS = ("minhas", "equipe", "folhas")  # ordem no grupo Feixe
_PROP = "feixe/modulo"  # propriedade do nó da árvore de camadas que diz de que módulo ele é


def _grupo_feixe(projeto) -> QgsLayerTreeGroup:
    raiz = projeto.layerTreeRoot()
    return raiz.findGroup(GRUPO) or raiz.insertGroup(0, GRUPO)


def _tirar_modulo(projeto, grupo: QgsLayerTreeGroup, modulo: str) -> None:
    for no in [n for n in grupo.children() if n.customProperty(_PROP) == modulo]:
        if isinstance(no, QgsLayerTreeGroup):
            projeto.removeMapLayers([c.layerId() for c in no.findLayers()])
            grupo.removeChildNode(no)
        else:
            projeto.removeMapLayer(no.layerId())


def _posicao(grupo: QgsLayerTreeGroup, modulo: str) -> int:
    """Índice onde entra o módulo: depois dos nós dos módulos que vêm antes dele."""
    antes = MODULOS[: MODULOS.index(modulo)]
    return sum(1 for n in grupo.children() if n.customProperty(_PROP) in antes)


def _camadas_do_modulo(amb, authcfg, eu, responsaveis, temas, modulo) -> List[QgsVectorLayer]:
    uf = eu.get("uf")
    if modulo == "minhas":
        minhas = _camada(
            amb, authcfg, "Minhas cargas", "vw_carga_trabalho", "id_carga_trabalho", "", "minhas_cargas.qml"
        )
        _so_concluido_editavel(minhas)
        return [minhas]
    if modulo == "equipe":
        por_resp = _camada(
            amb, authcfg, "Cargas por responsável", "carga_trabalho", "id",
            _filtro_passagens(uf) + " AND responsavel IS NOT NULL",
        )  # fmt: skip
        _por_responsavel(por_resp, responsaveis)
        filtro_disp = _filtro_passagens(uf) + " AND responsavel IS NULL"
        disponiveis = _camada(amb, authcfg, "Cargas disponíveis", "carga_trabalho", "id", filtro_disp)
        disponiveis.setRenderer(
            QgsSingleSymbolRenderer(
                QgsFillSymbol.createSimple(
                    {"color": "255,200,0,90", "outline_color": "200,140,0,255", "style": "b_diagonal"}
                )
            )
        )
        return [por_resp, disponiveis]
    camadas = []
    for t in temas:
        filtro = " AND ".join(p for p in (_filtro_uf(uf), f"id_tema = {int(t['id'])}") if p)
        camadas.append(_camada(amb, authcfg, f"Folhas · {t['nome']}", "ctrl_lote", "id_lote", filtro, "folhas.qml"))
    return camadas


def montar(
    amb: Ambiente,
    authcfg: str,
    eu: Dict,
    responsaveis: List[Dict],
    temas: List[Dict],
    modulos: Optional[List[str]] = None,
) -> Dict:
    """(Re)monta o grupo Feixe no topo do projeto, todo ou só os módulos pedidos (minhas, equipe, folhas).

    Cada módulo carregado de novo substitui só os seus nós; os outros ficam como estão. "equipe" é só do supervisor:
    em "todas" ele some para quem não é. `eu` é o objeto de GET /api/eu; `responsaveis` vem de
    `dados.cargas.responsaveis_atuais`; `temas` de `dados.lotes.temas_com_lotes`. Devolve o nome e a contagem de
    feições de cada camada carregada.
    """
    if not authcfg:
        raise RuntimeError("usuário e senha ainda não configurados")
    supervisor = "supervisor" in (eu.get("papeis") or [])
    pedidos = [m for m in MODULOS if m in (modulos or MODULOS) and (m != "equipe" or supervisor)]
    projeto = QgsProject.instance()
    grupo = _grupo_feixe(projeto)
    carregadas = []
    for m in pedidos:
        _tirar_modulo(projeto, grupo, m)
        camadas = _camadas_do_modulo(amb, authcfg, eu, responsaveis, temas, m)
        pos = _posicao(grupo, m)
        if m == "folhas":
            sub = grupo.insertGroup(pos, "Folhas")
            sub.setCustomProperty(_PROP, m)
            ligado = max(temas, key=lambda t: t.get("lotes") or 0)["id"] if temas else None
            for t, c in zip(temas, camadas):
                projeto.addMapLayer(c, False)
                sub.addLayer(c).setItemVisibilityChecked(t["id"] == ligado)
        else:
            for k, c in enumerate(camadas):
                projeto.addMapLayer(c, False)
                grupo.insertLayer(pos + k, c).setCustomProperty(_PROP, m)
        carregadas += camadas
    return {"modulos": pedidos, "camadas": [{"nome": c.name(), "feicoes": c.featureCount()} for c in carregadas]}


# --- Minhas cargas: seleção e recarga (B2) ---------------------------------------------------------------------------


def camada_minhas() -> Optional[QgsVectorLayer]:
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    if grupo is None:
        return None
    for no in grupo.findLayers():
        if no.layer() is not None and no.layer().name() == "Minhas cargas":
            return no.layer()
    return None


def carga_selecionada() -> Optional[int]:
    """Id da primeira carga selecionada na camada Minhas cargas, ou None."""
    camada = camada_minhas()
    if camada is None:
        return None
    for f in camada.getSelectedFeatures():
        return int(f["id_carga_trabalho"])
    return None


def selecionar_carga(id_carga: int) -> None:
    camada = camada_minhas()
    if camada is not None:
        camada.selectByExpression(f'"id_carga_trabalho" = {int(id_carga)}')


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


# --- Prévia das cargas geradas pela grade (B4) -----------------------------------------------------------------------
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
    """Ids das cargas selecionadas nas camadas do grupo Feixe que têm cargas (id da carga em `id` ou
    `id_carga_trabalho`)."""
    grupo = QgsProject.instance().layerTreeRoot().findGroup(GRUPO)
    ids, camadas_ = set(), []
    for no in grupo.findLayers() if grupo else []:
        camada = no.layer()
        if not isinstance(camada, QgsVectorLayer) or not camada.selectedFeatureCount():
            continue
        campo = "id_carga_trabalho" if camada.fields().indexOf("id_carga_trabalho") >= 0 else "id"
        if camada.fields().indexOf("geocodigo") < 0 and campo == "id":
            continue  # não é camada de cargas (Folhas)
        ids.update(int(f[campo]) for f in camada.getSelectedFeatures())
        camadas_.append(camada.name())
    return {"ids": sorted(ids), "camadas": camadas_}
