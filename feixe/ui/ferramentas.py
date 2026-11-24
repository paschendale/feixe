"""Ferramentas do Feixe no mapa do QGIS: escolher folhas pelo clique ou pelo retângulo e ler o polígono da seleção
(B3)."""

from __future__ import annotations

from typing import Callable, Dict

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

SIRGAS = QgsCoordinateReferenceSystem("EPSG:4674")


class FerramentaFolha(QgsMapTool):
    """Escolher folhas no mapa (Novas folhas). Clique: a folha do ponto. Ctrl ou Shift e arrastar: um retângulo, e
    todas as folhas que ele cobre. Arrastar sem tecla move o mapa, como a mão do QGIS, para não trocar de ferramenta
    no meio da escolha. Devolve as coordenadas em SIRGAS 2000 geográfico. Fica ligada até a pessoa trocar de ferramenta
    ou fechar o diálogo no painel."""

    ARRASTO_MINIMO = 4  # pixels: menos que isso é clique

    def __init__(self, canvas, ao_clicar: Callable[[float, float], None], ao_retangulo: Callable[[QgsRectangle], None]):
        super().__init__(canvas)
        self._ao_clicar = ao_clicar
        self._ao_retangulo = ao_retangulo
        self._inicio = None
        self._botao = Qt.LeftButton
        self._retangulo = False
        self._arrastou = False
        self._banda = None
        self.setCursor(Qt.CrossCursor)

    def _para_sirgas(self):
        origem = self.canvas().mapSettings().destinationCrs()
        return None if origem == SIRGAS else QgsCoordinateTransform(origem, SIRGAS, QgsProject.instance())

    def _limpar_banda(self):
        if self._banda is not None:
            self._banda.reset(QgsWkbTypes.PolygonGeometry)

    def canvasPressEvent(self, e):  # noqa: N802
        # No Mac, Ctrl é Qt.MetaModifier (Qt.ControlModifier é a tecla Command) e o sistema entrega Ctrl e clique
        # como botão direito: os dois valem como "Ctrl e arrastar".
        ctrl_mac = e.button() == Qt.RightButton and bool(e.modifiers() & Qt.MetaModifier)
        if e.button() != Qt.LeftButton and not ctrl_mac:
            return
        self._botao = e.button()
        self._inicio = e.pos()
        self._retangulo = ctrl_mac or bool(e.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier | Qt.MetaModifier))
        self._arrastou = False

    def canvasMoveEvent(self, e):  # noqa: N802
        if self._inicio is None or not (e.buttons() & self._botao):
            return
        if not self._arrastou and (e.pos() - self._inicio).manhattanLength() < self.ARRASTO_MINIMO:
            return
        self._arrastou = True
        if not self._retangulo:
            self.canvas().panAction(e)
            return
        if self._banda is None:
            self._banda = QgsRubberBand(self.canvas(), QgsWkbTypes.PolygonGeometry)
            self._banda.setColor(QColor(19, 81, 180, 60))
            self._banda.setStrokeColor(QColor("#1351B4"))
            self._banda.setWidth(2)
        conv = self.toMapCoordinates
        self._banda.setToGeometry(QgsGeometry.fromRect(QgsRectangle(conv(self._inicio), conv(e.pos()))), None)

    def canvasReleaseEvent(self, e):  # noqa: N802
        if e.button() != self._botao or self._inicio is None:
            return
        inicio, self._inicio = self._inicio, None
        if self._arrastou and not self._retangulo:
            self.canvas().panActionEnd(e.pos())
            return
        tr = self._para_sirgas()
        if self._arrastou:
            self._limpar_banda()
            ret = QgsRectangle(self.toMapCoordinates(inicio), self.toMapCoordinates(e.pos()))
            self._ao_retangulo(tr.transformBoundingBox(ret) if tr else ret)
            return
        ponto = self.toMapCoordinates(e.pos())
        if tr:
            ponto = tr.transform(ponto)
        self._ao_clicar(ponto.x(), ponto.y())

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key_Escape and self._inicio is not None:
            self._inicio = None
            self._limpar_banda()

    def deactivate(self):
        self._limpar_banda()
        self._inicio = None
        super().deactivate()


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
