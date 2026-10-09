"""Configuração do plugin: ambiente ativo e conexão PostGIS do QGIS usada em cada ambiente.

Guardada no QgsSettings (perfil do usuário). Nunca guarda senha: a senha fica na conexão PostGIS
do QGIS, protegida pelo Authentication Manager.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from qgis.core import QgsSettings

AMBIENTES = {
    "dev": ("Desenvolvimento", "#b45309"),
    "homologacao": ("Homologação", "#7c3aed"),
    "producao": ("Produção", "#15803d"),
}
_PREFIXO = "feixe"


@dataclass
class Config:
    ambiente: str = "producao"
    conexoes: dict = None  # ambiente -> nome da conexão PostGIS no QGIS
    porta: int = 0  # 0 = porta livre aleatória

    def __post_init__(self):
        if self.conexoes is None:
            self.conexoes = {}
        if self.ambiente not in AMBIENTES:
            self.ambiente = "producao"

    @property
    def conexao(self) -> str:
        return self.conexoes.get(self.ambiente, "")

    @property
    def rotulo_ambiente(self) -> str:
        return AMBIENTES[self.ambiente][0]

    @property
    def cor_ambiente(self) -> str:
        return AMBIENTES[self.ambiente][1]

    def pasta_workspace(self, usuario: str) -> str:
        """Pasta do workspace local: separada por ambiente e por usuário, nunca misturada."""
        base = os.path.join(os.path.expanduser("~"), ".feixe", self.ambiente, usuario or "anonimo")
        os.makedirs(base, exist_ok=True)
        return base


def carregar() -> Config:
    s = QgsSettings()
    cfg = Config(
        ambiente=s.value(f"{_PREFIXO}/ambiente", "producao"),
        conexoes={a: s.value(f"{_PREFIXO}/conexoes/{a}", "") for a in AMBIENTES},
        porta=int(s.value(f"{_PREFIXO}/porta", 0)),
    )
    return cfg


def salvar(cfg: Config) -> None:
    s = QgsSettings()
    s.setValue(f"{_PREFIXO}/ambiente", cfg.ambiente)
    for a, nome in cfg.conexoes.items():
        s.setValue(f"{_PREFIXO}/conexoes/{a}", nome)
    s.setValue(f"{_PREFIXO}/porta", cfg.porta)
