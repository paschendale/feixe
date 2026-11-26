#!/usr/bin/env bash
# Executa no host de dev. Restaura um dump parcial (alguns schemas) num dos bancos de dev, substituindo esses schemas.
# Os schemas listados são removidos (CASCADE) antes; o resto do banco fica como está.
#
# Uso: FEIXE_DB_PASSWORD=... restaurar_recorte.sh <feixe-ggc|feixe-ccar> <dump> <pre.sql> <post.sql> <schema,...>
#
# <pre.sql>/<post.sql> são as seções pre-data e post-data do dump já adaptadas por adaptar_ddl.py (na máquina de
# desenvolvimento). Os dados são carregados pelo pg_restore do container feixe-ccar (versão nova o bastante para ler
# dumps do pg_dump 17), apontando para o banco de destino pela rede interna dos containers.
set -uo pipefail
: "${FEIXE_DB_PASSWORD:?}"
destino=$1 dump=$2 pre=$3 post=$4 schemas=$5
T=/tmp/recorte
docker exec feixe-ccar rm -rf "$T" && docker exec feixe-ccar mkdir -p "$T"
docker cp "$dump" "feixe-ccar:$T/dump"
docker cp "$pre" "feixe-ccar:$T/pre.sql"
docker cp "$post" "feixe-ccar:$T/post.sql"

px() { docker exec -e PGPASSWORD="$FEIXE_DB_PASSWORD" feixe-ccar psql -h "$destino" -U postgres -d gisdb_edgv30 -X -q "$@"; }
resumo() { grep -E "ERROR|error" | sed -E 's/[0-9]+//g; s/"[^"]*"/"x"/g' | sort | uniq -c | sort -rn | head -8; }

echo "== [$destino] removendo $schemas"
IFS=, read -r -a lista <<<"$schemas"
for s in "${lista[@]}"; do
    px -c "SET client_min_messages = warning; DROP SCHEMA IF EXISTS $s CASCADE;" 2>&1 | resumo
done
echo "== pre-data"
px -v ON_ERROR_STOP=0 -f "$T/pre.sql" 2>&1 | resumo
echo "== dados"
docker exec -e PGPASSWORD="$FEIXE_DB_PASSWORD" feixe-ccar pg_restore -h "$destino" -U postgres -d gisdb_edgv30 \
    --section=data --no-owner --no-privileges --jobs=2 "$T/dump" 2>&1 | resumo
echo "== post-data"
px -v ON_ERROR_STOP=0 -f "$T/post.sql" 2>&1 | resumo
docker exec feixe-ccar rm -rf "$T"
echo "== [$destino] ok"
