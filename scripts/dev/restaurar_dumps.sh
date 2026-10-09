#!/usr/bin/env bash
# Executa no disbelief. Espera os dumps em /home/victor/feixe-dumps e a DDL adaptada em /home/victor/feixe-dumps/sql.
set -uo pipefail
: "${FEIXE_DB_PASSWORD:?}"
D=/home/victor/feixe-dumps
export PGPASSWORD="$FEIXE_DB_PASSWORD"
docker cp "$D/sql" feixe-ccar:/tmp/sql
docker cp "$D/banco_df.sql" feixe-ccar:/tmp/banco_df.sql
docker cp "$D/banco_rj.sql" feixe-ccar:/tmp/banco_rj.sql
psqlx() { # psqlx <host> <arquivo sql>
  docker exec -e PGPASSWORD="$PGPASSWORD" feixe-ccar psql -h "$1" -U postgres -d gisdb_edgv30 -q -v ON_ERROR_STOP=0 -f "/tmp/sql/$2" 2>&1 | grep -E "ERROR" | sed -E 's/[0-9]+//g' | sort | uniq -c | sort -rn | head -8
  echo "   [$1] $2 aplicado"
}
datax() { # datax <host> <dump> [-n schema ...]
  local host=$1 dump=$2; shift 2
  docker exec -e PGPASSWORD="$PGPASSWORD" feixe-ccar pg_restore -h "$host" -U postgres -d gisdb_edgv30 --section=data --no-owner --no-privileges --jobs=2 "$@" "/tmp/$dump" 2>&1 | grep -E "error" | sed -E 's/"[^"]*"/"x"/g; s/[0-9]+//g' | sort | uniq -c | sort -rn | head -5
  echo "   [$host] dados de $dump ($*) carregados"
}
echo "== GGC (9.6): mapcartctrl/mapcartsis + bc100ggcdf_*"
psqlx feixe-ggc mc_pre.sql
psqlx feixe-ggc df_pre.sql
datax feixe-ggc banco_rj.sql -n mapcartctrl -n mapcartsis
datax feixe-ggc banco_df.sql
psqlx feixe-ggc mc_post.sql
psqlx feixe-ggc df_post.sql
echo "== CCAR (17): mapcartctrl/mapcartsis + bc100grj_*"
psqlx feixe-ccar rj_pre.sql
datax feixe-ccar banco_rj.sql
psqlx feixe-ccar rj_post.sql
docker exec feixe-ccar rm -rf /tmp/sql /tmp/banco_df.sql /tmp/banco_rj.sql
echo "== resumo"
for h in feixe-ggc feixe-ccar; do
  docker exec -e PGPASSWORD="$PGPASSWORD" feixe-ccar psql -h $h -U postgres -d gisdb_edgv30 -tAc "select '$h', n.nspname, c.relkind, count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname ~ '^(bc100|mapcart)' and c.relkind in ('r','v') group by 1,2,3 order by 2,3"
done
docker exec -e PGPASSWORD="$PGPASSWORD" feixe-ccar psql -h feixe-ggc -U postgres -d gisdb_edgv30 -tAc "select 'ggc carga_trabalho', count(*) from bc100ggcdf_apoio.carga_trabalho union all select 'ggc cq_amostra', count(*) from bc100ggcdf_apoio.cq_amostra union all select 'ggc hid_trecho_drenagem_l', count(*) from bc100ggcdf_base.hid_trecho_drenagem_l union all select 'ggc t_usuario', count(*) from mapcartctrl.t_usuario union all select 'ggc v_articulacao_scn_100000', count(*) from mapcartctrl.v_articulacao_scn_100000"
docker exec -e PGPASSWORD="$PGPASSWORD" feixe-ccar psql -h feixe-ccar -U postgres -d gisdb_edgv30 -tAc "select 'ccar t_usuario', count(*) from mapcartctrl.t_usuario union all select 'ccar t_articulacao_scn', count(*) from mapcartctrl.t_articulacao_scn union all select 'ccar t_projeto', count(*) from mapcartctrl.t_projeto"
