"""Rotas da API por assunto. Cada módulo expõe `registrar(r, ctx)` e usa só `core.dados` para falar com o banco."""

from __future__ import annotations

MODULOS: list = []


def registrar(r, ctx) -> None:
    for modulo in MODULOS:
        modulo.registrar(r, ctx)
