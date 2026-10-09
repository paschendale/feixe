#!/usr/bin/env bash
# Aplica o espelho do Feixe numa GGC (feixe/db/ggc) apontando para a CCAR e confere, objeto por objeto, que o
# count(*) no espelho é igual ao da CCAR e que o espelho recusa escrita.
#
# Uso: scripts/db/testar_espelho.sh <conninfo_ggc> <conninfo_ccar> [dblink|fdw|ambos]
#
# Como a GGC alcança a CCAR (pode ser diferente de como esta máquina alcança) vem do ambiente:
#   ESPELHO_HOST, ESPELHO_PORTA, ESPELHO_BANCO, ESPELHO_CONTA, ESPELHO_SENHA
# No dev os dois containers estão na mesma rede: ESPELHO_HOST=feixe-ccar ESPELHO_PORTA=5432.
#
# Com "ambos" (padrão) testa dblink e depois postgres_fdw, e deixa a variante postgres_fdw instalada.
set -euo pipefail

GGC="${1:?uso: testar_espelho.sh <conninfo_ggc> <conninfo_ccar> [dblink|fdw|ambos]}"
CCAR="${2:?uso: testar_espelho.sh <conninfo_ggc> <conninfo_ccar> [dblink|fdw|ambos]}"
QUAIS="${3:-ambos}"
: "${ESPELHO_HOST:?}" "${ESPELHO_PORTA:?}" "${ESPELHO_BANCO:?}" "${ESPELHO_CONTA:?}" "${ESPELHO_SENHA:?}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../feixe/db/ggc" && pwd)"
OBJETOS="schema_version tema fase atividade fluxo fluxo_etapa usuario_feixe calendario lote lote_etapa
lote_etapa_hist carga_trabalho cq_plano cq_amostra cq_inspecao sync_log ctrl_lote_etapa ctrl_lote"

psqlg() { PGOPTIONS="-c client_min_messages=warning" psql "$GGC" -X -q -v ON_ERROR_STOP=1 "$@"; }

aplicar() { # aplicar <variante>
    local v=$1
    echo "== espelho via $v"
    psqlg -f "$DIR/remover.sql"
    psqlg -v ccar_host="$ESPELHO_HOST" -v ccar_porta="$ESPELHO_PORTA" -v ccar_banco="$ESPELHO_BANCO" \
          -v conta="$ESPELHO_CONTA" -v senha="$ESPELHO_SENHA" -f "$DIR/001_server_$v.sql"
    psqlg -f "$DIR/002_foreign_tables_$v.sql"
    psqlg -f "$DIR/003_views_compat.sql"
}

contagens() { # contagens <conninfo>: "objeto contagem" por linha, numa consulta só
    local sql="" o
    for o in $OBJETOS; do
        sql+="${sql:+ UNION ALL }SELECT '$o', count(*) FROM mapcartacomp.$o"
    done
    psql "$1" -X -A -t -F ' ' -v ON_ERROR_STOP=1 -c "$sql"
}

conferir() {
    local falhas=0 o g c
    local lg lc
    lg=$(contagens "$GGC") || return 1
    lc=$(contagens "$CCAR") || return 1
    for o in $OBJETOS; do
        g=$(awk -v o="$o" '$1 == o {print $2}' <<<"$lg")
        c=$(awk -v o="$o" '$1 == o {print $2}' <<<"$lc")
        if [[ "$g" == "$c" ]]; then
            printf '   %-16s %8s = %s\n' "$o" "$g" "$c"
        else
            printf '   %-16s %8s != %s  <- DIFERENTE\n' "$o" "$g" "$c"
            falhas=$((falhas + 1))
        fi
    done
    echo "   vw_carga_trabalho: $(psql "$GGC" -X -A -t -c "SELECT count(*) FROM mapcartacomp.vw_carga_trabalho") \
linhas no espelho (filtrada pelo usuário conectado na GGC)"
    if psql "$GGC" -X -q -c "BEGIN; INSERT INTO mapcartacomp.tema (nome) VALUES ('nao_pode'); ROLLBACK;" \
        >/dev/null 2>&1; then
        echo "   ERRO: o espelho aceitou escrita"
        falhas=$((falhas + 1))
    else
        echo "   escrita recusada no espelho: ok"
    fi
    return $falhas
}

case "$QUAIS" in
    dblink | fdw) variantes=("$QUAIS") ;;
    ambos) variantes=(dblink fdw) ;;
    *) echo "variante desconhecida: $QUAIS" >&2 && exit 2 ;;
esac
for v in "${variantes[@]}"; do
    aplicar "$v" || { echo "falha ao aplicar o espelho via $v" >&2; exit 1; }
    conferir || { echo "espelho via $v diverge da CCAR" >&2; exit 1; }
done
echo "espelho ok"
