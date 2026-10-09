import json
import threading
import urllib.error
import urllib.request

import pytest
from feixe.server.api import Contexto, criar_roteador
from feixe.server.http import ServidorLocal
from feixe.server.sse import Broker


@pytest.fixture
def servidor(tmp_path):
    (tmp_path / "index.html").write_text("<h1>feixe</h1>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    broker = Broker()
    srv = ServidorLocal(criar_roteador(Contexto(status=lambda: {"online": True})), broker, str(tmp_path)).iniciar()
    yield srv
    srv.parar()


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def test_estatico_e_spa(servidor):
    status, headers, corpo = _get(servidor.origem + "/")
    assert status == 200 and b"feixe" in corpo and "text/html" in headers["Content-Type"]
    status, headers, _ = _get(servidor.origem + "/assets/app.js")
    assert status == 200 and "immutable" in headers["Cache-Control"]
    status, _, corpo = _get(servidor.origem + "/qualquer/rota")
    assert status == 200 and b"feixe" in corpo  # SPA fallback
    status, _, _ = _get(servidor.origem + "/../../etc/passwd")
    assert status in (200, 403)  # normalizado para dentro da raiz ou recusado, nunca fora dela


def test_api_exige_token(servidor):
    status, _, _ = _get(servidor.origem + "/api/status")
    assert status == 401
    status, _, corpo = _get(servidor.origem + "/api/status", {"X-Feixe-Token": servidor.token})
    assert status == 200 and json.loads(corpo)["online"] is True
    status, _, _ = _get(servidor.origem + f"/api/status?token={servidor.token}")
    assert status == 200


def test_origem_estranha_recusada(servidor):
    status, _, _ = _get(
        servidor.origem + "/api/status", {"X-Feixe-Token": servidor.token, "Origin": "http://evil.example"}
    )
    assert status == 403
    status, _, _ = _get(servidor.origem + "/api/status", {"X-Feixe-Token": servidor.token, "Origin": servidor.origem})
    assert status == 200


def test_sse_recebe_evento(servidor):
    recebido = {}

    def ler():
        req = urllib.request.Request(servidor.origem + f"/api/eventos?token={servidor.token}")
        with urllib.request.urlopen(req, timeout=10) as r:
            linhas = []
            for linha in r:
                linhas.append(linha.decode("utf-8"))
                texto = "".join(linhas)
                if "event: estado" in texto and texto.endswith("\n\n"):
                    recebido["ok"] = texto
                    break

    t = threading.Thread(target=ler, daemon=True)
    t.start()
    for _ in range(50):
        if servidor.broker.conectados:
            break
        threading.Event().wait(0.05)
    servidor.broker.publicar("estado", {"online": True})
    t.join(timeout=5)
    assert "event: conectado" in recebido["ok"] and '"online": true' in recebido["ok"]
