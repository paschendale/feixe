"""Feixe: controle e acompanhamento de cargas de trabalho da produção cartográfica (IBGE/CCAR)."""


def classFactory(iface):  # noqa: N802 (nome exigido pelo QGIS)
    from .plugin import FeixePlugin

    return FeixePlugin(iface)
