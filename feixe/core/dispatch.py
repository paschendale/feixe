"""Executa uma função na thread principal do Qt e espera o resultado.

Tudo que toca objetos do QGIS (camadas, canvas, projeto) precisa rodar na thread principal. O servidor
HTTP roda em threads próprias e usa `na_thread_principal` para pedir essas operações.
"""

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, Optional

from qgis.PyQt.QtCore import QCoreApplication, QObject, Qt, QThread, pyqtSignal


class _Despachante(QObject):
    chamada = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.chamada.connect(self._executar, Qt.QueuedConnection)

    def _executar(self, item):
        fn, args, kwargs, fut = item
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as e:  # noqa: BLE001
            fut.set_exception(e)


_despachante: Optional[_Despachante] = None


def iniciar() -> None:
    """Chamar uma vez, na thread principal (no initGui do plugin)."""
    global _despachante
    if _despachante is None:
        _despachante = _Despachante()


def encerrar() -> None:
    global _despachante
    _despachante = None


def na_thread_principal(fn: Callable[..., Any], *args, timeout: float = 30.0, **kwargs) -> Any:
    app = QCoreApplication.instance()
    if app is None or QThread.currentThread() is app.thread():
        return fn(*args, **kwargs)
    if _despachante is None:
        raise RuntimeError("despachante não iniciado; chame dispatch.iniciar() na thread principal")
    fut: concurrent.futures.Future = concurrent.futures.Future()
    _despachante.chamada.emit((fn, args, kwargs, fut))
    return fut.result(timeout=timeout)
