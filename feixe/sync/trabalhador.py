"""Sincronização em segundo plano (C3, D-111 item 2): uma thread que roda `sincronizar()` quando alguém a acorda.

Quem acorda: cada escrita da execução (concluir, desfazer, o puxar da fila), as escritas da supervisão na CCAR (para
o workspace de quem também executa receber logo o que mudou), o `QTimer` de rede do plugin (a cada minuto, o
periódico) e o primeiro uso (workspace vazio). Rajadas viram uma sincronização só: cada `acordar` adia a rodada para
`atraso` segundos depois do último pedido, mas nunca mais que `atraso_max` depois do primeiro (quem conclui uma carga
a cada dois segundos não fica sem enviar). `acordar(0)` roda já.

Sem QGIS e sem banco: recebe a função que sincroniza (a `Sincronizacao.sincronizar`, que nunca levanta exceção e
avisa o plugin por `ao_terminar`, que manda para a thread principal por sinal e para o painel pelo SSE). Se uma
sincronização já está rodando (o botão da barra, a rota), tenta de novo logo depois.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional

ATRASO = 1.5  # segundos depois do último pedido
ATRASO_MAX = 8.0  # segundos depois do primeiro pedido de uma rajada
REPETIR_EM_ANDAMENTO = 2.0


class Trabalhador:
    def __init__(
        self,
        sincronizar: Callable[[], Dict[str, Any]],
        atraso: float = ATRASO,
        atraso_max: float = ATRASO_MAX,
        relogio: Callable[[], float] = time.monotonic,
    ):
        self._sincronizar = sincronizar
        self.atraso = atraso
        self.atraso_max = atraso_max
        self._relogio = relogio
        self._cond = threading.Condition()
        self._prazo: Optional[float] = None
        self._primeiro: Optional[float] = None
        self._urgente = False  # a rodada marcada foi pedida para já: um pedido com atraso não a adia
        self._parar = False
        self._thread: Optional[threading.Thread] = None
        self.rodadas = 0
        self.ultimo: Optional[Dict[str, Any]] = None

    def iniciar(self) -> Trabalhador:
        if self._thread is None or not self._thread.is_alive():
            self._parar = False
            self._thread = threading.Thread(target=self._laco, name="feixe-sincronizacao", daemon=True)
            self._thread.start()
        return self

    def parar(self, espera: float = 5.0) -> None:
        with self._cond:
            self._parar = True
            self._cond.notify_all()
        if self._thread is not None:
            self._thread.join(espera)
            self._thread = None

    @property
    def vivo(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def pendente(self) -> bool:
        """Há uma rodada marcada que ainda não começou."""
        return self._prazo is not None

    def acordar(self, atraso: Optional[float] = None) -> None:
        """Pede uma sincronização daqui a `atraso` segundos (padrão: o do trabalhador), juntando com os pedidos
        próximos."""
        agora = self._relogio()
        atraso = self.atraso if atraso is None else atraso
        with self._cond:
            if self._primeiro is None:
                self._primeiro = agora
            if atraso <= 0:
                self._prazo, self._urgente = agora, True
            elif self._prazo is None or not self._urgente:
                self._prazo = max(self._prazo or 0.0, min(agora + atraso, self._primeiro + self.atraso_max))
            self._cond.notify_all()

    def _laco(self) -> None:
        while True:
            with self._cond:
                while not self._parar:
                    if self._prazo is None:
                        self._cond.wait()
                        continue
                    falta = self._prazo - self._relogio()
                    if falta <= 0:
                        break
                    self._cond.wait(falta)
                if self._parar:
                    return
                self._prazo = self._primeiro = None
                self._urgente = False
            try:
                r = self._sincronizar()
            except Exception as e:  # noqa: BLE001 - a thread não pode morrer; o desfecho fica no resultado
                r = {"estado": "erro", "mensagem": str(e)}
            self.rodadas += 1
            self.ultimo = r
            if (r or {}).get("estado") == "em_andamento":
                self.acordar(REPETIR_EM_ANDAMENTO)
