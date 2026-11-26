#!/usr/bin/env python3
"""Gera os GRANTs do mapcartacomp para as roles que a DBA criou ou escolheu.

Uso:
    python3 scripts/db/gerar_grants.py --roles atualizacao.txt [--consulta consulta.txt] > grants.sql

Cada arquivo tem uma role por linha (linhas vazias e começadas por # são ignoradas; '-' lê da entrada padrão). Segue o
padrão da DBA para schemas novos: uma role de administração, dona do schema (não precisa de GRANT), uma role de
atualização, que agrupa SELECT, INSERT, UPDATE e DELETE nas tabelas, e uma role de consulta, só com SELECT.

- `--roles`: roles de atualização. Quem usa o Feixe para trabalhar (executar, avaliar, supervisionar) é membro de uma
  delas.
- `--consulta`: roles só de leitura (SELECT em tabelas e views), para quem só acompanha por fora do plugin.

Nenhuma role é criada: o script só concede privilégios às que vierem nas listas. Reaplicar depois de cada migração
nova (tabela nova precisa de GRANT) e quando uma role nova precisar de acesso; GRANT repetido não tem efeito.

Todas as roles de atualização recebem o mesmo acesso. O banco não distingue papéis nem UFs nesta versão: quem é
operador, avaliador, supervisor ou gerente é decidido pelo plugin, a partir dos perfis do SGBC (mapcartctrl) e de
usuario_feixe, e não pelas roles do banco.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Iterable, List, Optional

NOME_VALIDO = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")

TABELAS = [
    "schema_version", "tema", "fase", "atividade", "fluxo", "fluxo_etapa", "fluxo_etapa_atividade", "cq_elemento",
    "usuario_feixe", "calendario", "lote", "lote_etapa", "lote_etapa_hist", "carga_trabalho", "cq_plano", "cq_amostra",
    "cq_inspecao", "sync_log", "fila_folha",
]  # fmt: skip
# Tabelas de configuração fixa: só leitura para os usuários (alteradas pelas migrações).
SO_LEITURA = ["schema_version", "fase"]
VIEWS_LEITURA = ["ctrl_lote_etapa", "ctrl_lote", "vw_carga_supervisao"]
VIEWS_EDITAVEIS = {
    "vw_carga_trabalho": "SELECT, UPDATE",
    "vw_cq_amostra": "SELECT, UPDATE",
    "vw_cq_amostra_all": "SELECT, UPDATE, DELETE",
    "vw_cq_inspecao": "SELECT, INSERT, UPDATE, DELETE",
}


def ler_roles(linhas: Iterable[str]) -> List[str]:
    roles = []
    for bruta in linhas:
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if not NOME_VALIDO.match(linha):
            raise ValueError(f"nome de role inválido: {linha}")
        if linha not in roles:
            roles.append(linha)
    return roles


def _q(nome: str) -> str:
    return f"mapcartacomp.{nome}"


def gerar(roles: List[str], consulta: Optional[List[str]] = None) -> str:
    escrita = [t for t in TABELAS if t not in SO_LEITURA]
    saida = [
        "-- GRANTs do mapcartacomp gerados por scripts/db/gerar_grants.py",
        "-- Idempotente: GRANT repetido não tem efeito.",
        "BEGIN;",
    ]
    for role in roles:
        r = f'"{role}"'
        saida.append(f"\n-- {role}")
        saida.append(f"GRANT USAGE ON SCHEMA mapcartacomp TO {r};")
        saida.append(f"GRANT SELECT ON {', '.join(_q(t) for t in SO_LEITURA + VIEWS_LEITURA)} TO {r};")
        saida.append(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(_q(t) for t in escrita)} TO {r};")
        saida.append(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA mapcartacomp TO {r};")
        for view, privs in VIEWS_EDITAVEIS.items():
            saida.append(f"GRANT {privs} ON {_q(view)} TO {r};")
    for role in consulta or []:
        r = f'"{role}"'
        saida.append(f"\n-- {role} (consulta)")
        saida.append(f"GRANT USAGE ON SCHEMA mapcartacomp TO {r};")
        objetos = TABELAS + VIEWS_LEITURA + list(VIEWS_EDITAVEIS)
        saida.append(f"GRANT SELECT ON {', '.join(_q(t) for t in objetos)} TO {r};")
    saida.append("\nCOMMIT;")
    return "\n".join(saida) + "\n"


def _ler_arquivo(caminho: str) -> List[str]:
    if caminho == "-":
        return ler_roles(sys.stdin)
    with open(caminho, encoding="utf-8") as f:
        return ler_roles(f)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--roles", required=True, help="roles de atualização, uma por linha ('-' para a entrada padrão)")
    p.add_argument("--consulta", help="roles só de leitura, uma por linha")
    a = p.parse_args(argv)
    roles = _ler_arquivo(a.roles)
    consulta = _ler_arquivo(a.consulta) if a.consulta else []
    if not roles:
        print("nenhuma role na lista", file=sys.stderr)
        return 1
    sys.stdout.write(gerar(roles, consulta))
    return 0


if __name__ == "__main__":
    sys.exit(main())
