"""Configuração do usuário: só a credencial (usuário e senha), guardada no Authentication Manager do QGIS.

O banco vem do ambiente chumbado no build (`core.ambiente`). O plugin guarda no QgsSettings apenas o id da
configuração de autenticação; a senha fica no banco de autenticação do QGIS, protegido pela senha mestra.
"""

from __future__ import annotations

import os
from typing import Optional

from qgis.core import QgsApplication, QgsAuthMethodConfig, QgsSettings

from .ambiente import Ambiente

_PREFIXO = "feixe"


def _chave(amb: Ambiente) -> str:
    return f"{_PREFIXO}/{amb.nome}/authcfg"


def authcfg_id(amb: Ambiente) -> str:
    return QgsSettings().value(_chave(amb), "") or ""


def credenciais(amb: Ambiente) -> Optional[tuple]:
    """(usuario, senha) ou None se ainda não configurado."""
    cid = authcfg_id(amb)
    if not cid:
        return None
    cfg = QgsAuthMethodConfig()
    ok, cfg = QgsApplication.authManager().loadAuthenticationConfig(cid, cfg, True)
    if not ok or not cfg.isValid():
        return None
    return cfg.config("username", ""), cfg.config("password", "")


def salvar_credenciais(amb: Ambiente, usuario: str, senha: str) -> str:
    """Cria ou atualiza a configuração 'Basic' do Authentication Manager e devolve o id."""
    am = QgsApplication.authManager()
    cid = authcfg_id(amb)
    cfg = QgsAuthMethodConfig()
    if cid:
        ok, cfg = am.loadAuthenticationConfig(cid, cfg, True)
        if not ok:
            cfg = QgsAuthMethodConfig()
            cid = ""
    cfg.setName(f"Feixe ({amb.rotulo})")
    cfg.setMethod("Basic")
    cfg.setConfig("username", usuario)
    cfg.setConfig("password", senha)
    cfg.setConfig("realm", amb.descricao_banco)
    if cid:
        cfg.setId(cid)
        if not am.updateAuthenticationConfig(cfg):
            raise RuntimeError("o QGIS não conseguiu atualizar a credencial no Authentication Manager")
    else:
        if not am.storeAuthenticationConfig(cfg):
            raise RuntimeError("o QGIS não conseguiu guardar a credencial no Authentication Manager")
        cid = cfg.id()
        QgsSettings().setValue(_chave(amb), cid)
    registrar_conexao_qgis(amb, cid)
    return cid


def registrar_conexao_qgis(amb: Ambiente, cid: str) -> str:
    """Cadastra (ou atualiza) uma conexão PostGIS no QGIS com a mesma credencial, para o usuário carregar camadas."""
    nome = f"Feixe ({amb.rotulo})"
    s = QgsSettings()
    base = f"PostgreSQL/connections/{nome}/"
    s.setValue(base + "host", amb.host)
    s.setValue(base + "port", str(amb.porta))
    s.setValue(base + "database", amb.banco)
    s.setValue(base + "authcfg", cid)
    s.setValue(base + "sslmode", {"disable": 0, "allow": 1, "prefer": 1, "require": 2}.get(amb.sslmode, 1))
    s.setValue(base + "saveUsername", "false")
    s.setValue(base + "savePassword", "false")
    s.setValue(base + "estimatedMetadata", "true")
    return nome


def pasta_workspace(amb: Ambiente, usuario: str) -> str:
    """Workspace local separado por ambiente e por usuário, nunca misturado."""
    base = os.path.join(os.path.expanduser("~"), ".feixe", amb.nome, usuario or "anonimo")
    os.makedirs(base, exist_ok=True)
    return base
