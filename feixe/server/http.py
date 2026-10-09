"""Servidor HTTP local do plugin: arquivos estáticos do front, API JSON e stream de eventos (SSE).

Só biblioteca padrão. Escuta apenas em 127.0.0.1, numa porta livre, com um token por sessão:
- a página é aberta com `?token=...` e guarda o token; toda chamada à API manda `X-Feixe-Token`;
- `EventSource` não aceita cabeçalhos, então o stream aceita o token na query;
- requisições com cabeçalho `Origin` de outra origem são recusadas (páginas de outros sites não falam com o plugin).
"""

from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlsplit

from .api import Roteador
from .sse import Broker

_PAGINA_SEM_FRONT = """<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Feixe</title>
<body style="font-family:sans-serif;margin:3rem"><h1>Feixe</h1>
<p>O servidor local está no ar, mas o front não foi compilado (<code>make web</code>).</p>
<p><a href="/api/status">/api/status</a></p></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    server: ServidorLocal
    protocol_version = "HTTP/1.1"

    # --- utilidades -------------------------------------------------------------------------
    def log_message(self, fmt, *args):  # silencia o log padrão no stderr
        if self.server.verboso:
            super().log_message(fmt, *args)

    def _origem_ok(self) -> bool:
        origem = self.headers.get("Origin")
        return origem is None or origem == self.server.origem

    def _token_ok(self, query) -> bool:
        enviado = self.headers.get("X-Feixe-Token") or (query.get("token") or [None])[0]
        return bool(enviado) and secrets.compare_digest(enviado, self.server.token)

    def _responder_json(self, status: int, obj) -> None:
        corpo = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _responder_bytes(self, status: int, corpo: bytes, tipo: str, cache: str = "no-cache") -> None:
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _ler_corpo(self):
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho == 0:
            return None
        bruto = self.rfile.read(tamanho)
        try:
            return json.loads(bruto.decode("utf-8"))
        except ValueError:
            return None

    # --- roteamento -------------------------------------------------------------------------
    def _tratar(self):
        partes = urlsplit(self.path)
        query = parse_qs(partes.query)
        caminho = partes.path
        if not self._origem_ok():
            return self._responder_json(403, {"erro": "origem não permitida"})
        if caminho == "/api/eventos":
            if not self._token_ok(query):
                return self._responder_json(401, {"erro": "token inválido"})
            return self._stream_eventos()
        if caminho.startswith("/api/"):
            if not self._token_ok(query):
                return self._responder_json(401, {"erro": "token inválido"})
            corpo = self._ler_corpo() if self.command in ("POST", "PUT", "PATCH") else None
            query_simples = {k: v[0] for k, v in query.items()}
            status, obj = self.server.roteador.despachar(self.command, caminho, query_simples, corpo)
            return self._responder_json(status, obj)
        return self._estatico(caminho)

    def _estatico(self, caminho: str):
        raiz = self.server.pasta_estatica
        if not raiz or not os.path.isdir(raiz):
            return self._responder_bytes(200, _PAGINA_SEM_FRONT.encode("utf-8"), "text/html; charset=utf-8")
        rel = os.path.normpath(caminho.lstrip("/")) if caminho not in ("", "/") else "index.html"
        alvo = os.path.join(raiz, rel)
        if not os.path.abspath(alvo).startswith(os.path.abspath(raiz)):
            return self._responder_json(403, {"erro": "caminho inválido"})
        if not os.path.isfile(alvo):
            alvo = os.path.join(raiz, "index.html")  # SPA: qualquer rota desconhecida volta ao index
        tipo = mimetypes.guess_type(alvo)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            tipo += "; charset=utf-8"
        cache = "public, max-age=31536000, immutable" if "/assets/" in alvo.replace("\\", "/") else "no-cache"
        with open(alvo, "rb") as f:
            return self._responder_bytes(200, f.read(), tipo, cache)

    def _stream_eventos(self):
        broker = self.server.broker
        fila = broker.inscrever()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(Broker.formatar("conectado", json.dumps({"ok": True})))
            self.wfile.flush()
            while not self.server.encerrando:
                try:
                    evento, corpo = fila.get(timeout=15)
                except Exception:  # noqa: BLE001  (timeout: manda um comentário para manter a conexão viva)
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                self.wfile.write(Broker.formatar(evento, corpo))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            broker.cancelar(fila)

    def do_GET(self):  # noqa: N802
        self._tratar()

    def do_HEAD(self):  # noqa: N802
        self._tratar()

    def do_POST(self):  # noqa: N802
        self._tratar()

    def do_PUT(self):  # noqa: N802
        self._tratar()

    def do_PATCH(self):  # noqa: N802
        self._tratar()

    def do_DELETE(self):  # noqa: N802
        self._tratar()


class ServidorLocal(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self, roteador: Roteador, broker: Broker, pasta_estatica: Optional[str], porta: int = 0, verboso=False
    ):
        super().__init__(("127.0.0.1", porta), _Handler)
        self.roteador = roteador
        self.broker = broker
        self.pasta_estatica = pasta_estatica
        self.token = secrets.token_urlsafe(32)
        self.verboso = verboso
        self.encerrando = False
        self._thread: Optional[threading.Thread] = None

    @property
    def porta(self) -> int:
        return self.server_address[1]

    @property
    def origem(self) -> str:
        return f"http://127.0.0.1:{self.porta}"

    @property
    def url_abertura(self) -> str:
        return f"{self.origem}/?token={self.token}"

    def iniciar(self) -> ServidorLocal:
        self._thread = threading.Thread(target=self.serve_forever, name="feixe-http", daemon=True)
        self._thread.start()
        return self

    def parar(self) -> None:
        self.encerrando = True
        self.broker.publicar("encerrando", {})
        self.shutdown()
        self.server_close()
        if self._thread:
            self._thread.join(timeout=5)
