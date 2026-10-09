#!/usr/bin/env bash
# Aplica as migrações de feixe/db/ccar que faltam num banco e registra cada uma em mapcartacomp.schema_version.
#
# Uso: scripts/db/aplicar.sh [--ensaio] <conninfo> [ate_versao]
#
#   <conninfo>    string de conexão do psql (URL postgresql://... ou "host=... dbname=...")
#   [ate_versao]  aplica só até esta versão (padrão: todas)
#   --ensaio      aplica tudo numa transação e desfaz no fim (ROLLBACK): prova que o SQL roda naquele servidor
#                 sem deixar nada criado. É como se verifica a compatibilidade com o PostgreSQL 9.6 das GGCs.
#
# Todas as migrações pendentes rodam numa única transação: ou entram todas, ou nenhuma.
# Rodar de novo sem migrações novas não faz nada.
set -euo pipefail

ENSAIO=0
if [[ "${1:-}" == "--ensaio" ]]; then
    ENSAIO=1
    shift
fi
CONN="${1:?uso: aplicar.sh [--ensaio] <conninfo> [ate_versao]}"
ATE="${2:-999999}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../feixe/db/ccar" && pwd)"

psqlq() { psql "$CONN" -X -A -t -q -v ON_ERROR_STOP=1 "$@"; }

tem_tabela=$(psqlq -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                       WHERE n.nspname = 'mapcartacomp' AND c.relname = 'schema_version'")
atual=0
if [[ "$tem_tabela" == "1" ]]; then
    atual=$(psqlq -c "SELECT coalesce(max(versao), 0) FROM mapcartacomp.schema_version")
fi

pendentes=()  # compatível com o bash 3.2 do macOS
for f in "$DIR"/[0-9][0-9][0-9]_*.sql; do
    nome="$(basename "$f")"
    v=$((10#${nome:0:3}))
    if ((v > atual && v <= ATE)); then
        pendentes+=("$f")
    fi
done

if ((${#pendentes[@]} == 0)); then
    echo "nada a aplicar: banco na versão $atual"
    exit 0
fi

{
    echo "BEGIN;"
    for f in "${pendentes[@]}"; do
        nome="$(basename "$f")"
        v=$((10#${nome:0:3}))
        echo "\\echo aplicando $nome"
        echo "\\i '$f'"
        echo "INSERT INTO mapcartacomp.schema_version (versao, nome) VALUES ($v, '${nome%.sql}');"
    done
    if ((ENSAIO)); then
        echo "ROLLBACK;"
    else
        echo "COMMIT;"
    fi
} | PGOPTIONS="-c client_min_messages=warning" psql "$CONN" -X -q -v ON_ERROR_STOP=1

final=$(basename "${pendentes[${#pendentes[@]}-1]}")
final=$((10#${final:0:3}))
if ((ENSAIO)); then
    echo "ensaio ok: ${#pendentes[@]} migrações ($((atual + 1)) a $final) aplicadas e desfeitas"
else
    echo "aplicadas ${#pendentes[@]} migrações: versão $atual -> $final"
fi
