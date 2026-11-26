#!/usr/bin/env python3
"""Ambiente de dev: `config/ambientes.json` com host, porta e banco tirados da URL `FEIXE_CCAR`.

O host de dev não fica no repositório: vem da variável `FEIXE_CCAR` ou do `.dev.env` da raiz (fora do Git). Sem
nenhum dos dois (CI), fica o que está no `ambientes.json`.

Uso: python3 scripts/dev/ambiente_dev.py feixe/ambiente.json
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
from typing import Optional

RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def url_ccar(raiz: str = RAIZ) -> Optional[str]:
    if os.environ.get("FEIXE_CCAR"):
        return os.environ["FEIXE_CCAR"]
    try:
        with open(os.path.join(raiz, ".dev.env"), encoding="utf-8") as f:
            for linha in f:
                if linha.startswith("FEIXE_CCAR="):
                    return linha.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def carregar(raiz: str = RAIZ) -> dict:
    with open(os.path.join(raiz, "config", "ambientes.json"), encoding="utf-8") as f:
        d = json.load(f)["dev"]
    url = url_ccar(raiz)
    if url:
        u = urllib.parse.urlparse(url)
        d.update(host=u.hostname or d["host"], porta=u.port or d["porta"], banco=u.path.lstrip("/") or d["banco"])
    return d


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        json.dump(carregar(), f, indent=2)
