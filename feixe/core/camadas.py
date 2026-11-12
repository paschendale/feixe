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
    camada.setRenderer(QgsCategorizedSymbolRenderer("responsavel", categorias))


def montar(amb: Ambiente, authcfg: str, eu: Dict, responsaveis: List[Dict], temas: List[Dict]) -> Dict:
    """(Re)monta o grupo Feixe no topo do projeto. Montar de novo substitui o grupo, não duplica.

    `eu` é o objeto de GET /api/eu; `responsaveis` vem de `dados.cargas.responsaveis_atuais` (só usado para
    supervisor); `temas` de `dados.lotes.temas_com_lotes`. Devolve o nome e a contagem de feições de cada camada.
    """
    if not authcfg:
        raise RuntimeError("usuário e senha ainda não configurados")
    uf = eu.get("uf")
    projeto = QgsProject.instance()
    raiz = projeto.layerTreeRoot()
    antigo = raiz.findGroup(GRUPO)
    if antigo is not None:
        projeto.removeMapLayers([c.layerId() for c in antigo.findLayers()])
        raiz.removeChildNode(antigo)
    grupo: QgsLayerTreeGroup = raiz.insertGroup(0, GRUPO)

    camadas = []
    minhas = _camada(amb, authcfg, "Minhas cargas", "vw_carga_trabalho", "id_carga_trabalho", "", "minhas_cargas.qml")
    _so_concluido_editavel(minhas)
    camadas.append(minhas)
    if "supervisor" in (eu.get("papeis") or []):
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
        camadas += [por_resp, disponiveis]
    for c in camadas:
        projeto.addMapLayer(c, False)
        grupo.addLayer(c)

    sub = grupo.addGroup("Folhas")
    ligado = max(temas, key=lambda t: t.get("lotes") or 0)["id"] if temas else None
    for t in temas:
        filtro = " AND ".join(p for p in (_filtro_uf(uf), f"id_tema = {int(t['id'])}") if p)
        folhas = _camada(amb, authcfg, f"Folhas · {t['nome']}", "ctrl_lote", "id_lote", filtro, "folhas.qml")
        projeto.addMapLayer(folhas, False)
        sub.addLayer(folhas).setItemVisibilityChecked(t["id"] == ligado)
        camadas.append(folhas)
    return {"camadas": [{"nome": c.name(), "feicoes": c.featureCount()} for c in camadas]}


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
