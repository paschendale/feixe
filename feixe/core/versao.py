"""Versão do plugin, lida do metadata.txt para não existir em dois lugares."""

from __future__ import annotations

import configparser
import os

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def versao_plugin() -> str:
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join(_RAIZ, "metadata.txt"), encoding="utf-8")
    return cfg.get("general", "version", fallback="0.0.0")


def raiz_plugin() -> str:
    return _RAIZ
