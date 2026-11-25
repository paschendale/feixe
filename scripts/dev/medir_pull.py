#!/usr/bin/env python3
"""S-03: cronometra o pull inicial (C2) contra a CCAR de dev e confere a sincronização de ponta a ponta.

Uso, no Mac, pelo caminho do plugin:
    /Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/medir_pull.py [vezes]
ou em qualquer Python 3.9+ só com psycopg2 (ex.: num container no disbelief):
    python3 scripts/dev/medir_pull.py [vezes]

Mede, em workspaces novos numa pasta temporária (apagada no fim):
(a) o escopo de uma pessoa: a que tem mais cargas no DF migrado;
(b) toda a carga_trabalho do DF (escopo que ninguém tem, só para dimensionar), com o resto do espelho igual;
e, para cada um, o pull seguinte sem mudanças. Com o pacote qgis à mão, as conexões são as do plugin (`db.transacao`
com `connect_timeout` curto) e o script roda também `Sincronizacao` com a conta do .dev.env e contra uma porta fechada,
para ver o "offline". Sem ele, conecta direto pela URL FEIXE_CCAR do .dev.env (ou do ambiente).
Só lê o banco: nada é gravado na CCAR.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import statistics
import sys
import tempfile
import time
import urllib.parse

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, RAIZ)

import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402
from feixe.core.dados import ExecutorPg  # noqa: E402
from feixe.sync import pull  # noqa: E402
from feixe.sync.sincronizar import Sincronizacao  # noqa: E402
from feixe.sync.workspace import Workspace  # noqa: E402

try:
    from feixe.core import ambiente, db
except ImportError:  # sem o QGIS: conexão direta
    db = None


def url_dev() -> str:
    if os.environ.get("FEIXE_CCAR"):
        return os.environ["FEIXE_CCAR"]
    with open(os.path.join(RAIZ, ".dev.env"), encoding="utf-8") as f:
        for linha in f:
            if linha.startswith("FEIXE_CCAR="):
                return linha.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit("FEIXE_CCAR não está no .dev.env")


URL = url_dev()
_u = urllib.parse.urlparse(URL)
CONTA, SENHA = urllib.parse.unquote(_u.username), urllib.parse.unquote(_u.password)


def ambiente_dev(**mudar):
    with open(os.path.join(RAIZ, "config", "ambientes.json"), encoding="utf-8") as f:
        d = json.load(f)["dev"]
    d.update(mudar)
    return ambiente.de_dict(d)


@contextlib.contextmanager
def _direta():
    conn = psycopg2.connect(URL, connect_timeout=5)
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield ExecutorPg(cur)
    finally:
        conn.close()


def transacao():
    return db.transacao(ambiente_dev(), CONTA, SENHA, timeout_conexao=5) if db else _direta()


def puxar(ws, **kw):
    with transacao() as rx:
        rx.executar("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        return pull.puxar(ws, rx, **kw)


def medir(nome, temp, vezes, **kw):
    tempos, ccar, grav = [], [], []
    for i in range(vezes):
        with Workspace.abrir("dev", f"medida{i}", "DF", raiz=os.path.join(temp, nome)) as ws:
            r = puxar(ws, **kw)
            tempos.append(r["duracao_s"])
            ccar.append(r["duracao_ccar_s"])
            grav.append(r["duracao_gravacao_s"])
            de_novo = puxar(ws, **kw)
            tamanho = sum(os.path.getsize(p) for p in (ws.caminho, ws.caminho + "-wal") if os.path.exists(p))
    cargas = r["tabelas"]["carga_trabalho"]["inseridas"]
    print(
        f"{nome}: {cargas} cargas, {r['linhas']} linhas no total, workspace {tamanho / 1e6:.1f} MB; "
        f"pull inicial mediana {statistics.median(tempos):.2f} s (min {min(tempos):.2f}, max {max(tempos):.2f}; "
        f"CCAR {statistics.median(ccar):.2f} s, gravação {statistics.median(grav):.2f} s); "
        f"pull sem mudanças {de_novo['duracao_s']:.2f} s, {de_novo['recebidas']} linhas"
    )


def ponta_a_ponta(temp):
    """Sincronizacao pelo caminho do plugin, com a conta do .dev.env (workspace dela) e com a porta fechada."""
    amb, fechada = ambiente_dev(), ambiente_dev(porta=1)
    with Workspace.abrir("dev", CONTA, "DF", raiz=os.path.join(temp, "sinc")) as ws:
        for rotulo, a, rede in (("CCAR de dev", amb, True), ("porta fechada", fechada, True),
                                ("porta fechada, sem o teste de rede", fechada, False)):  # fmt: skip
            s = Sincronizacao(
                lambda: ws,
                lambda a=a: db.transacao(a, CONTA, SENHA, timeout_conexao=5),
                alcancavel=(lambda a=a: db.alcancavel(a)) if rede else None,
            )
            r = s.sincronizar()
            print(f"sincronizar, {rotulo}: {r['estado']} em {r['duracao_s']:.2f} s ({r['mensagem'] or 'ok'})")


def main():
    vezes = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    temp = tempfile.mkdtemp(prefix="feixe-s03-")
    try:
        for rotulo in ("conexão nova e SELECT 1", "SELECT 1 de novo"):
            t = time.monotonic()
            with transacao() as ex:
                ex.um("SELECT 1 AS x")
            print(f"{rotulo}: {time.monotonic() - t:.3f} s")
        with transacao() as ex:
            quem = ex.um(
                "SELECT responsavel FROM mapcartacomp.carga_trabalho WHERE uf = 'DF' AND responsavel IS NOT NULL "
                "GROUP BY 1 ORDER BY count(*) DESC LIMIT 1"
            )["responsavel"]
        medir("a_pessoa", temp, vezes, usuario=quem)
        # Toda a carga_trabalho da UF: só para medir (S-03), não é escopo de ninguém.
        medir("b_uf", temp, vezes, usuario=quem, onde=pull.escopos(lambda a: f"{a}.uf = %(uf)s"))
        if db:
            ponta_a_ponta(temp)
    finally:
        if db:
            db.esquecer()
        shutil.rmtree(temp, ignore_errors=True)


if __name__ == "__main__":
    main()
