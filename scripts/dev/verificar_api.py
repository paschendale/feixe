#!/usr/bin/env python3
"""Verifica a API do plugin ponta a ponta, sem abrir o QGIS: QGIS headless, credencial no Authentication Manager,
servidor local e GET /api/eu contra o banco de dev.

Uso (Mac, com o QGIS-LTR):
    /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/verificar_api.py [--conta-sem-uf] [--servir N]

Lê o banco de config/ambientes.json (dev) e o usuário e a senha de FEIXE_CCAR no .dev.env da raiz. Usa um perfil do
QGIS e um banco de autenticação temporários, apagados no fim: nada é gravado no perfil do usuário.

Confere: /api/status responde; /api/eu devolve a conta conectada (current_user), com nome, UF (nula quando a lotação
é nula ou fora do padrão, sem erro), elegibilidade e papéis vindos só do SGBC e de usuario_feixe. Com
--conta-sem-uf, carrega também, pelo mesmo código da rota, uma conta real com lotação nula do banco de dev. Com
--servir N, deixa o servidor no ar por N segundos e imprime a URL do painel (com o build do front em feixe/web/dist).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMP = tempfile.mkdtemp(prefix="feixe-verificar-")
os.environ["QGIS_CUSTOM_CONFIG_PATH"] = os.path.join(TEMP, "perfil")
os.environ["QGIS_AUTH_DB_DIR_PATH"] = os.path.join(TEMP, "auth")
os.makedirs(os.environ["QGIS_AUTH_DB_DIR_PATH"])
sys.path.insert(0, RAIZ)

# Python do QGIS-LTR do Mac: prefixo e dados do PROJ ao lado do executável (.../Contents/MacOS/bin/python3).
_MACOS = os.path.dirname(os.path.dirname(os.path.abspath(sys.executable)))
_PROJ = os.path.join(os.path.dirname(_MACOS), "Resources", "proj")
if os.path.isdir(_PROJ):
    os.environ.setdefault("PROJ_LIB", _PROJ)
    os.environ.setdefault("PROJ_DATA", _PROJ)

from feixe.core import ambiente, config, db, papeis  # noqa: E402
from feixe.server.api import Contexto, criar_roteador  # noqa: E402
from feixe.server.http import ServidorLocal  # noqa: E402
from feixe.server.sse import Broker  # noqa: E402
from qgis.core import QgsApplication  # noqa: E402
from scripts.dev.ambiente_dev import carregar as ambiente_dev_dict  # noqa: E402


def _credencial_dev():
    with open(os.path.join(RAIZ, ".dev.env"), encoding="utf-8") as f:
        for linha in f:
            if linha.startswith("FEIXE_CCAR="):
                u = urllib.parse.urlparse(linha.split("=", 1)[1].strip().strip("'\""))
                return urllib.parse.unquote(u.username), urllib.parse.unquote(u.password)
    raise SystemExit("FEIXE_CCAR não está no .dev.env")


def _get(srv, caminho):
    req = urllib.request.Request(srv.origem + caminho, headers={"X-Feixe-Token": srv.token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def main() -> int:
    QgsApplication.setPrefixPath(_MACOS, True)
    app = QgsApplication([], False)
    app.initQgis()
    srv = None
    try:
        am = QgsApplication.authManager()
        if not am.setMasterPassword("feixe-verificacao", True):
            raise SystemExit("não foi possível iniciar o Authentication Manager temporário")
        amb = ambiente.de_dict(ambiente_dev_dict())
        usuario, senha = _credencial_dev()
        config.salvar_credenciais(amb, usuario, senha)
        assert config.credenciais(amb) == (usuario, senha), "credencial não foi relida do Authentication Manager"

        def consultar(sql, params=None):
            return db.consultar(amb, sql, params)

        def status():
            return {
                "online": True,
                "ambiente": amb.nome,
                "rotulo_ambiente": amb.rotulo,
                "cor_ambiente": amb.cor,
                "banco": amb.descricao_banco,
                "credencial": True,
                "usuario": usuario,
                "detalhe": "verificação headless",
            }

        ctx = Contexto(status=status, consultar=consultar)
        srv = ServidorLocal(criar_roteador(ctx), Broker(), os.path.join(RAIZ, "feixe", "web", "dist")).iniciar()

        status, obj = _get(srv, "/api/status")
        assert status == 200 and obj["online"], obj
        status, eu = _get(srv, "/api/eu")
        print("GET /api/eu ->", status)
        print(json.dumps(eu, ensure_ascii=False, indent=2))
        assert status == 200, eu
        assert eu["conta"] == usuario, f"conta {eu['conta']!r}, esperado {usuario!r}"
        assert eu["uf"] is None or (len(eu["uf"]) == 2 and eu["uf"].isupper())
        assert eu["uf"] == papeis.uf_da_lotacao(eu["lotacao"])
        assert set(eu["papeis"]) <= set(papeis.PRECEDENCIA)
        if not eu["elegivel"]:
            assert eu["papeis"] == [] and eu["papel"] is None

        if "--conta-sem-uf" in sys.argv:
            linhas = consultar(
                "SELECT nom_contausuario FROM mapcartctrl.t_usuario WHERE dsc_lotacao IS NULL "
                "ORDER BY cod_usuario LIMIT 1"
            )
            assert linhas, "nenhuma conta com lotação nula no banco de dev"
            outra = papeis.carregar(consultar, linhas[0]["nom_contausuario"])
            print("conta com lotação nula ->", json.dumps(outra, ensure_ascii=False))
            assert outra["lotacao"] is None and outra["uf"] is None and outra["cadastrada"]
        if "--servir" in sys.argv:
            # Mantém o servidor no ar para abrir o painel no navegador e conferir o cabeçalho.
            segundos = int(sys.argv[sys.argv.index("--servir") + 1])
            print("painel:", srv.url_abertura, flush=True)
            time.sleep(segundos)
        print("ok")
        return 0
    finally:
        if srv:
            srv.parar()
        app.exitQgis()
        shutil.rmtree(TEMP, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
