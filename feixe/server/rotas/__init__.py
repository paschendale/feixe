"""Rotas da API por assunto. Cada módulo expõe `registrar(r, ctx)` e usa só `core.dados` para falar com o banco."""

from __future__ import annotations

from . import camadas, cargas, cq, filas, fluxos, lotes, painel, referencias, sync_log

# `cq` antes de `fluxos`: /api/lote_etapas/{id}/cq_plano casaria com /api/lote_etapas/{id}/{acao}.
MODULOS: list = [camadas, cargas, filas, lotes, cq, fluxos, painel, referencias, sync_log]


def registrar(r, ctx) -> None:
    for modulo in MODULOS:
        modulo.registrar(r, ctx)
