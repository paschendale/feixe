"""Rotas da API por assunto. Cada módulo expõe `registrar(r, ctx)` e usa só `core.dados` para falar com o banco."""

from __future__ import annotations

from . import camadas, cargas, filas, fluxos, lotes, painel, referencias, sync_log

MODULOS: list = [camadas, cargas, filas, lotes, fluxos, painel, referencias, sync_log]


def registrar(r, ctx) -> None:
    for modulo in MODULOS:
        modulo.registrar(r, ctx)
