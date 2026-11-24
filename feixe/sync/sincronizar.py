"""Sincronização de uma conta: push (C3) e depois pull (C2), e o estado que a barra e o painel mostram.

`Sincronizacao.sincronizar()` é a função que a rota `POST /api/sincronizar`, o botão da barra e (no C3) a thread de
segundo plano chamam. Uma de cada vez: se já há uma rodando, a segunda volta na hora com `em_andamento`. Nunca levanta
exceção para quem chamou: rede fora vira `offline`, o resto vira `erro` com a mensagem, e o estado guarda o desfecho.

Ordem: primeiro o push (o que a pessoa fez sai antes de o servidor mandar o dele; C3 entra em `_push`), depois o
pull, num retrato só da CCAR (REPEATABLE READ READ ONLY), para lotes, passagens e cargas chegarem coerentes entre si.

Não importa o QGIS nem `core.db`: o plugin injeta como abrir o workspace, como abrir uma transação na CCAR (com a
credencial do usuário e `connect_timeout` curto) e como testar a rede.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, ContextManager, Dict, Optional

from . import pull
from .workspace import Workspace, agora, de_iso, iso_exato

TIMEOUT_CONSULTA = "120s"  # por consulta, no pull; a conexão tem o connect_timeout do plugin


def _offline(e: BaseException) -> bool:
    try:
        import psycopg2
    except ImportError:  # pragma: no cover - o QGIS sempre traz
        return isinstance(e, OSError)
    return isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError, OSError))


class Sincronizacao:
    """Sincronização e estado de uma conta num ambiente.

    - `abrir_workspace()`: o `Workspace` da conta (o plugin guarda o aberto);
    - `remota()`: gerenciador de contexto com um executor psycopg2 numa transação nova na CCAR;
    - `alcancavel()`: teste barato de rede (TCP), para separar "sem rede" de "senha errada";
    - `ao_terminar(estado)`: chamado depois de cada sincronização, na thread que sincronizou (o plugin manda para a
      thread principal por sinal e publica no SSE)."""

    def __init__(
        self,
        abrir_workspace: Callable[[], Workspace],
        remota: Callable[[], ContextManager[Any]],
        alcancavel: Optional[Callable[[], bool]] = None,
        ao_terminar: Optional[Callable[[Dict], None]] = None,
    ):
        self._abrir_workspace = abrir_workspace
        self._remota = remota
        self._alcancavel = alcancavel
        self._ao_terminar = ao_terminar
        self._trava = threading.Lock()
        self._em_andamento = False
        self._online: Optional[bool] = None
        self._ultima_tentativa: Optional[str] = None
        self._ultimo: Optional[Dict] = None
        self._ws: Optional[Workspace] = None  # o último aberto, para o estado não precisar abrir (nem ir ao banco)

    # --- estado ----------------------------------------------------------------------------------------------------

    def marcar_rede(self, online: bool) -> None:
        """O teste de rede do plugin (QTimer) conta como a última notícia de online/offline."""
        self._online = online

    def usar(self, ws: Optional[Workspace]) -> None:
        """O plugin abriu (ou fechou, None) o workspace da conta: o estado passa a ler dele."""
        self._ws = ws

    def estado(self) -> Dict[str, Any]:
        """Para o indicador da barra e para o painel. Lê só o workspace já aberto (sem ele, pendências nulas): nunca
        vai ao banco, porque a barra e o `/api/status` pedem isto a toda hora, inclusive offline."""
        ultima = pendentes = None
        ws = self._ws
        if ws is not None:
            with ws.leitura() as ex:
                ultima = ex.meta("ultima_sincronizacao")
                pendentes = ex.um("SELECT count(*) AS n FROM outbox")["n"]
        u = self._ultimo or {}
        return {
            "online": self._online,
            "em_andamento": self._em_andamento,
            "ultima_sincronizacao": ultima,
            "ultima_tentativa": self._ultima_tentativa,
            "ultimo_estado": u.get("estado"),
            "mensagem": u.get("mensagem"),
            "pendentes": pendentes,
        }

    # --- sincronizar -----------------------------------------------------------------------------------------------

    def sincronizar(self) -> Dict[str, Any]:
        """Push e pull. Volta {estado: ok | offline | erro | em_andamento, mensagem, duracao_s, push, pull,
        pendentes, ultima_sincronizacao}."""
        if not self._trava.acquire(blocking=False):
            return {"estado": "em_andamento", "mensagem": "já há uma sincronização em andamento"}
        self._em_andamento = True
        t0 = time.monotonic()
        self._ultima_tentativa = iso_exato(agora())
        r: Dict[str, Any] = {"estado": "ok", "mensagem": None, "push": None, "pull": None}
        try:
            if self._alcancavel is not None and not self._alcancavel():
                r.update(estado="offline", mensagem="a CCAR não responde")
            else:
                ws = self._abrir_workspace()
                self._ws = ws
                r["push"] = self._push(ws)
                r["pull"] = self._pull(ws)
        except Exception as e:  # noqa: BLE001 - nada sobe para a UI: o desfecho fica no resultado e no estado
            offline = _offline(e) and (self._alcancavel is None or not self._alcancavel())
            r.update(estado="offline" if offline else "erro", mensagem=str(e).strip() or e.__class__.__name__)
        finally:
            self._em_andamento = False
            self._trava.release()
        r["duracao_s"] = round(time.monotonic() - t0, 3)
        self._online = r["estado"] != "offline"
        self._ultimo = r
        est = self.estado()
        r["pendentes"] = est["pendentes"]
        r["ultima_sincronizacao"] = est["ultima_sincronizacao"]
        if self._ao_terminar is not None:
            self._ao_terminar(est)
        return r

    def _push(self, ws: Workspace) -> Optional[Dict]:
        """Envio da outbox (C3). Até lá não envia nada: as pendências ficam e o pull não as sobrescreve."""
        return None

    def _pull(self, ws: Workspace) -> Dict:
        with self._remota() as rx:
            rx.executar("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            rx.executar(f"SET LOCAL statement_timeout = '{TIMEOUT_CONSULTA}'")
            conta = rx.um("SELECT current_user AS conta")["conta"]
            if conta != ws.usuario:
                raise RuntimeError(f"o workspace é de {ws.usuario}, mas a conexão é de {conta}")
            return pull.puxar(ws, rx)


def hora_local(iso: Optional[str]) -> Optional[str]:
    """Hora "hh:mm" no fuso da estação, para a dica da barra."""
    d = de_iso(iso) if iso else None
    return d.astimezone().strftime("%H:%M") if d else None
