"""Log do plugin no painel de mensagens do QGIS (aba "Feixe") e, fora do QGIS, no logging padrão."""

from __future__ import annotations

import logging

_ABA = "Feixe"
_log = logging.getLogger("feixe")


def _qgis_log(msg: str, nivel: int) -> bool:
    try:
        from qgis.core import Qgis, QgsMessageLog
    except ImportError:
        return False
    mapa = {
        logging.DEBUG: Qgis.Info,
        logging.INFO: Qgis.Info,
        logging.WARNING: Qgis.Warning,
        logging.ERROR: Qgis.Critical,
    }
    QgsMessageLog.logMessage(msg, _ABA, mapa.get(nivel, Qgis.Info))
    return True


def info(msg: str) -> None:
    _log.info(msg)
    _qgis_log(msg, logging.INFO)


def aviso(msg: str) -> None:
    _log.warning(msg)
    _qgis_log(msg, logging.WARNING)


def erro(msg: str) -> None:
    _log.error(msg)
    _qgis_log(msg, logging.ERROR)
