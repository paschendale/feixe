"""D-104: conexões reaproveitadas em `core.db`, contra o banco de dev (o mesmo usuário do .dev.env)."""

from __future__ import annotations

import json
import os
import sys
import types
import urllib.parse

import pytest

from tests.db.conftest import RAIZ, url

pytestmark = pytest.mark.db


@pytest.fixture
def conexao(psycopg2, monkeypatch):
    # core.db importa core.config, que precisa do QGIS. Fora dele, um qgis.core de mentira: aqui a credencial vai
    # explícita e o Authentication Manager não é usado.
    try:
        import qgis.core  # noqa: F401
    except ImportError:
        falso = types.ModuleType("qgis.core")
        falso.QgsApplication = falso.QgsAuthMethodConfig = falso.QgsSettings = object
        monkeypatch.setitem(sys.modules, "qgis", types.ModuleType("qgis"))
        monkeypatch.setitem(sys.modules, "qgis.core", falso)
    from feixe.core import ambiente, db

    u = urllib.parse.urlparse(url("FEIXE_CCAR"))
    with open(os.path.join(RAIZ, "config", "ambientes.json"), encoding="utf-8") as f:
        dados = json.load(f)["dev"]
    amb = ambiente.de_dict({**dados, "host": u.hostname, "porta": u.port, "banco": u.path.lstrip("/")})
    db.esquecer()
    yield db, amb, urllib.parse.unquote(u.username), urllib.parse.unquote(u.password)
    db.esquecer()


def _pid(db, amb, usuario, senha):
    with db.transacao(amb, usuario, senha) as ex:
        return ex.um("SELECT pg_backend_pid() AS pid")["pid"]


def test_reaproveita_e_se_recupera(conexao):
    db, amb, usuario, senha = conexao
    pid = _pid(db, amb, usuario, senha)
    assert _pid(db, amb, usuario, senha) == pid  # a segunda transação usa a mesma conexão

    # Erro de SQL desfaz a transação e a conexão continua servindo.
    with pytest.raises(Exception), db.transacao(amb, usuario, senha) as ex:  # noqa: B017
        ex.todos("SELECT * FROM tabela_que_nao_existe")
    assert _pid(db, amb, usuario, senha) == pid

    # Conexão derrubada no servidor: a transação que a pega falha, ela é descartada e a próxima abre outra.
    outra = db.conectar(amb, usuario, senha)
    with outra, outra.cursor() as cur:
        cur.execute("SELECT pg_terminate_backend(%s)", (pid,))
    outra.close()
    with pytest.raises(Exception), db.transacao(amb, usuario, senha) as ex:  # noqa: B017
        ex.todos("SELECT 1")
    novo = _pid(db, amb, usuario, senha)
    assert novo != pid and _pid(db, amb, usuario, senha) == novo

    db.esquecer()
    assert _pid(db, amb, usuario, senha) != novo  # esquecer fecha as ociosas
