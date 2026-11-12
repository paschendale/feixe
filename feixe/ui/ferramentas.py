"""Ferramentas do Feixe no mapa do QGIS: escolher folha pelo clique e ler o polígono da seleção (B3)."""

from __future__ import annotations

from typing import Callable, Dict

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtCore import Qt

SIRGAS = QgsCoordinateReferenceSystem("EPSG:4674")


class FerramentaFolha(QgsMapToolEmitPoint):
    """Cada clique esquerdo devolve (x, y) em SIRGAS 2000 geográfico. Fica ligada até a pessoa trocar de ferramenta."""

    def __init__(self, canvas, ao_clicar: Callable[[float, float], None]):
        super().__init__(canvas)
        self._ao_clicar = ao_clicar
        self.setCursor(Qt.CrossCursor)
        self.canvasClicked.connect(self._clicou)

    def _clicou(self, ponto, botao):
        if botao != Qt.LeftButton:
            return
        origem = self.canvas().mapSettings().destinationCrs()
        if origem != SIRGAS:
            ponto = QgsCoordinateTransform(origem, SIRGAS, QgsProject.instance()).transform(ponto)
        self._ao_clicar(ponto.x(), ponto.y())


class SemSelecao(Exception):
    pass


def selecao_wkt(camada) -> Dict:
    """União das feições selecionadas da camada (de polígonos), em SIRGAS 2000 geográfico, como WKT."""
    if not isinstance(camada, QgsVectorLayer) or camada.geometryType() != QgsWkbTypes.PolygonGeometry:
        raise SemSelecao("deixe ativa no QGIS uma camada de polígonos com as feições do lote selecionadas")
    geoms = [f.geometry() for f in camada.getSelectedFeatures() if f.hasGeometry()]
    if not geoms:
        raise SemSelecao(f"nenhuma feição selecionada na camada {camada.name()}")
    uniao = QgsGeometry.unaryUnion(geoms)
    if camada.crs() != SIRGAS:
        uniao.transform(QgsCoordinateTransform(camada.crs(), SIRGAS, QgsProject.instance()))
    return {"camada": camada.name(), "feicoes": len(geoms), "wkt": uniao.asWkt(8)}
