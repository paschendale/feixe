"""Server-Sent Events: fila por cliente conectado; o plugin publica, o navegador escuta.

Puro Python, sem dependência do QGIS, para ser testável fora dele.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Dict, List


class Broker:
    def __init__(self):
        self._clientes: List[queue.Queue] = []
        self._lock = threading.Lock()

    def inscrever(self) -> queue.Queue:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._clientes.append(q)
        return q

    def cancelar(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._clientes:
                self._clientes.remove(q)

    @property
    def conectados(self) -> int:
        with self._lock:
            return len(self._clientes)

    def publicar(self, evento: str, dados: Dict = None) -> None:
        corpo = json.dumps({"evento": evento, "dados": dados or {}, "em": time.time()}, ensure_ascii=False)
        with self._lock:
            clientes = list(self._clientes)
        for q in clientes:
            q.put((evento, corpo))

    @staticmethod
    def formatar(evento: str, corpo: str) -> bytes:
        return f"event: {evento}\ndata: {corpo}\n\n".encode()
