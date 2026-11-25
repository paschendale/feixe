"""Ambiente chumbado no build (dev, homologação ou produção): qual banco este plugin usa.

Lido de `feixe/ambiente.json`, gerado pelo `make deploy-local` (dev) ou pelo release (homologação/produção).
Sem dependência do QGIS, para ser testável. O usuário nunca escolhe ambiente: cada release é de um ambiente só.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

_ARQUIVO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ambiente.json")
_OBRIGATORIOS = ("nome", "rotulo", "cor", "host", "porta", "banco")


class AmbienteInvalido(Exception):
    pass


@dataclass(frozen=True)
class Ambiente:
    nome: str
    rotulo: str
    cor: str
    host: str
    porta: int
    banco: str
    sslmode: str = "prefer"

    @property
    def descricao_banco(self) -> str:
        return f"{self.host}:{self.porta}/{self.banco}"


def de_dict(d: dict) -> Ambiente:
    faltam = [k for k in _OBRIGATORIOS if k not in d or d[k] in ("", None)]
    if faltam:
        raise AmbienteInvalido(f"ambiente.json sem os campos: {', '.join(faltam)}")
    try:
        porta = int(d["porta"])
    except (TypeError, ValueError) as e:
        raise AmbienteInvalido("porta inválida") from e
    return Ambiente(
        nome=str(d["nome"]),
        rotulo=str(d["rotulo"]),
        cor=str(d["cor"]),
        host=str(d["host"]),
        porta=porta,
        banco=str(d["banco"]),
        sslmode=str(d.get("sslmode") or "prefer"),
    )


def carregar(caminho: str = _ARQUIVO) -> Ambiente:
    if not os.path.isfile(caminho):
        raise AmbienteInvalido(
            "este build do Feixe não tem ambiente.json; use `make deploy-local` (dev) ou um zip de release"
        )
    with open(caminho, encoding="utf-8") as f:
        return de_dict(json.load(f))
