#!/usr/bin/env python3
"""Gera os GRANTs do mapcartacomp para as roles de grupo que já existem (role_<projeto><unidade>_atua e _sup).

Uso:
    python3 scripts/db/gerar_grants.py --roles lista.txt > grants.sql

`lista.txt` tem uma role por linha (linhas vazias e começadas por # são ignoradas), por exemplo a saída de
    SELECT rolname FROM pg_roles WHERE rolname ~ '^role_.+_(atua|sup)$' ORDER BY 1;
Nenhuma role é criada: o script só concede privilégios às que vierem na lista.

Os GRANTs dizem quais tabelas e colunas cada role usa; quais linhas, quem decide é o RLS de 008_rls.sql.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Iterable, List

PADRAO = re.compile(r"^role_[a-z0-9_]+_(atua|sup)$")

TODAS = [
    "schema_version", "tema", "fase", "atividade", "fluxo", "fluxo_etapa", "usuario_feixe", "calendario",
    "lote", "lote_etapa", "lote_etapa_hist", "carga_trabalho", "cq_plano", "cq_amostra", "cq_inspecao", "sync_log",
]  # fmt: skip
VIEWS = ["vw_carga_trabalho", "vw_cq_amostra", "vw_cq_amostra_all", "vw_cq_inspecao", "ctrl_lote_etapa", "ctrl_lote"]

# Quem executa (_atua): lê tudo (o RLS limita à UF) e altera só as colunas do próprio trabalho.
ATUA_COLUNAS = {
    "carga_trabalho": ["concluido", "concluido_em"],
    "cq_amostra": ["status", "observacao", "avaliado_em", "avaliado_por"],
    "cq_inspecao": ["elemento", "anotacao", "geom", "tratado", "tratado_em", "tratado_por"],
}
ATUA_INSERE = ["cq_inspecao", "sync_log"]
ATUA_EXCLUI = ["cq_inspecao"]
ATUA_VIEWS_EDITAVEIS = {
    "vw_carga_trabalho": "UPDATE",
    "vw_cq_amostra": "UPDATE",
    "vw_cq_inspecao": "INSERT, UPDATE, DELETE",
}

# Supervisão (_sup): além do que _atua faz, planeja (o RLS limita à UF).
SUP_ESCREVE = [
    "tema", "atividade", "fluxo", "fluxo_etapa", "usuario_feixe", "calendario", "lote", "lote_etapa",
    "lote_etapa_hist", "carga_trabalho", "cq_plano", "cq_amostra", "cq_inspecao",
]  # fmt: skip
SUP_VIEWS_EDITAVEIS = {"vw_cq_amostra_all": "UPDATE, DELETE"}

SEQUENCIAS_ATUA = ["cq_inspecao_id_seq", "sync_log_id_seq"]


def ler_roles(linhas: Iterable[str]) -> List[str]:
    roles = []
    for bruta in linhas:
        linha = bruta.strip()
        if not linha or linha.startswith("#"):
            continue
        if not PADRAO.match(linha):
            raise ValueError(f"role fora do padrão role_<projeto><unidade>_atua|_sup: {linha}")
        if linha not in roles:
            roles.append(linha)
    return roles


def _q(nome: str) -> str:
    return f"mapcartacomp.{nome}"


def gerar(roles: List[str]) -> str:
    saida = [
        "-- GRANTs do mapcartacomp gerados por scripts/db/gerar_grants.py",
        "-- Idempotente: GRANT repetido não tem efeito.",
        "BEGIN;",
    ]
    for role in roles:
        papel = role.rsplit("_", 1)[1]
        r = f'"{role}"'
        saida.append(f"\n-- {role}")
        saida.append(f"GRANT USAGE ON SCHEMA mapcartacomp TO {r};")
        saida.append(f"GRANT SELECT ON {', '.join(_q(t) for t in TODAS + VIEWS)} TO {r};")
        for tabela, colunas in ATUA_COLUNAS.items():
            saida.append(f"GRANT UPDATE ({', '.join(colunas)}) ON {_q(tabela)} TO {r};")
        saida.append(f"GRANT INSERT ON {', '.join(_q(t) for t in ATUA_INSERE)} TO {r};")
        saida.append(f"GRANT DELETE ON {', '.join(_q(t) for t in ATUA_EXCLUI)} TO {r};")
        saida.append(f"GRANT USAGE ON SEQUENCE {', '.join(_q(s) for s in SEQUENCIAS_ATUA)} TO {r};")
        for view, privs in ATUA_VIEWS_EDITAVEIS.items():
            saida.append(f"GRANT {privs} ON {_q(view)} TO {r};")
        if papel == "sup":
            saida.append(f"GRANT INSERT, UPDATE, DELETE ON {', '.join(_q(t) for t in SUP_ESCREVE)} TO {r};")
            saida.append(f"GRANT USAGE ON ALL SEQUENCES IN SCHEMA mapcartacomp TO {r};")
            for view, privs in SUP_VIEWS_EDITAVEIS.items():
                saida.append(f"GRANT {privs} ON {_q(view)} TO {r};")
    saida.append("\nCOMMIT;")
    return "\n".join(saida) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--roles", required=True, help="arquivo com uma role por linha ('-' para a entrada padrão)")
    a = p.parse_args(argv)
    if a.roles == "-":
        roles = ler_roles(sys.stdin)
    else:
        with open(a.roles, encoding="utf-8") as f:
            roles = ler_roles(f)
    if not roles:
        print("nenhuma role na lista", file=sys.stderr)
        return 1
    sys.stdout.write(gerar(roles))
    return 0


if __name__ == "__main__":
    sys.exit(main())
