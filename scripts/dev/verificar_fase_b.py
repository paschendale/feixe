#!/usr/bin/env python3
"""Verificação headless da fase B contra o banco de dev, sem abrir o QGIS. Cada item acrescenta a sua seção.

Uso (Mac, com o QGIS-LTR):
    /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/verificar_fase_b.py [b0 b1 ...]

Sem argumentos roda todas as seções. Lê o banco de config/ambientes.json (dev) e o usuário e a senha de FEIXE_CCAR no
.dev.env da raiz. Usa perfil do QGIS e banco de autenticação temporários, apagados no fim. Tudo o que grava no banco é
desfeito ou apagado no fim de cada seção.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import urllib.parse

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMP = tempfile.mkdtemp(prefix="feixe-fase-b-")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = os.path.join(TEMP, "perfil")
os.environ["QGIS_AUTH_DB_DIR_PATH"] = os.path.join(TEMP, "auth")
os.makedirs(os.environ["QGIS_AUTH_DB_DIR_PATH"])
sys.path.insert(0, RAIZ)

_MACOS = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
_PROJ = os.path.join(os.path.dirname(_MACOS), "Resources", "proj")
if os.path.isdir(_PROJ):
    os.environ.setdefault("PROJ_LIB", _PROJ)
    os.environ.setdefault("PROJ_DATA", _PROJ)

from feixe.core import ambiente, db  # noqa: E402
from qgis.core import QgsApplication  # noqa: E402

SECOES = {}


def secao(nome):
    def registrar(fn):
        SECOES[nome] = fn
        return fn

    return registrar


def credencial_dev():
    with open(os.path.join(RAIZ, ".dev.env"), encoding="utf-8") as f:
        for linha in f:
            if linha.startswith("FEIXE_CCAR="):
                u = urllib.parse.urlparse(linha.split("=", 1)[1].strip().strip("'\""))
                return urllib.parse.unquote(u.username), urllib.parse.unquote(u.password)
    raise SystemExit("FEIXE_CCAR não está no .dev.env")


def ambiente_dev():
    with open(os.path.join(RAIZ, "config", "ambientes.json"), encoding="utf-8") as f:
        return ambiente.de_dict(json.load(f)["dev"])


def ok(msg):
    print(f"  ok  {msg}")


@secao("b0")
def b0(amb, usuario, senha):
    """Transação da camada de dados: commit ao sair, rollback em erro."""
    tabela = "public.feixe_verificar_b0"
    with db.transacao(amb, usuario, senha) as ex:
        ex.executar(f"CREATE TABLE {tabela} (x int)")
    try:
        try:
            with db.transacao(amb, usuario, senha) as ex:
                ex.executar(f"INSERT INTO {tabela} VALUES (1)")
                raise RuntimeError("erro de propósito")
        except RuntimeError:
            pass
        with db.transacao(amb, usuario, senha) as ex:
            assert ex.um(f"SELECT count(*) AS n FROM {tabela}")["n"] == 0
        ok("rollback em erro")
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar(f"INSERT INTO {tabela} VALUES (1)")
        with db.transacao(amb, usuario, senha) as ex:
            assert ex.um(f"SELECT count(*) AS n FROM {tabela}")["n"] == 1
        ok("commit ao sair")
    finally:
        with db.transacao(amb, usuario, senha) as ex:
            ex.executar(f"DROP TABLE IF EXISTS {tabela}")


def main():
    pedidas = sys.argv[1:] or list(SECOES)
    app = QgsApplication([], False)
    app.initQgis()
    try:
        amb = ambiente_dev()
        usuario, senha = credencial_dev()
        for nome in pedidas:
            print(f"{nome}: {SECOES[nome].__doc__.strip()}")
            SECOES[nome](amb, usuario, senha)
        print("tudo certo")
    finally:
        app.exitQgis()
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    main()
