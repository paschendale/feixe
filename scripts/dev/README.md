# scripts/dev

Ferramentas do ambiente de desenvolvimento (stack `feixe-db` no disbelief: `feixe-ggc` PostgreSQL 9.6 + PostGIS 3.2 na porta 5433 e `feixe-ccar` PostgreSQL 17 + PostGIS 3.5 na porta 5434). Senha e URLs em `.dev.env` na raiz do repo (symlink para `~/.config/feixe/dev.env`, fora do Git).

## Restaurar os dumps de apoio

Os dumps (`apoio/banco_df.sql` = GGC-DF, `apoio/banco_rj.sql` = CCAR) são do pg_dump 17 em formato custom. O `pg_restore` do 9.6 não lê esse formato, e os dumps referenciam schemas que não foram exportados (`dominios`, `bc100ggcdf_hist`, `bc100grj_hist`, `ccar`). Por isso a restauração é em três passos, com a DDL adaptada:

1. Na sua máquina, gerar as seções pre-data e post-data em SQL plano e adaptá-las com `adaptar_ddl.py` (remove constraints, FKs e triggers que dependem dos schemas ausentes; converte `EXECUTE FUNCTION` e colunas identity para o 9.6; acrescenta `CREATE SCHEMA` quando o `pg_restore -n` não emite):

```bash
D=apoio; O=/tmp/feixe-restore; mkdir -p $O
pg_restore --section=pre-data  --no-owner --no-privileges --no-tablespaces -f $O/df_pre.raw.sql  $D/banco_df.sql
pg_restore --section=post-data --no-owner --no-privileges                  -f $O/df_post.raw.sql $D/banco_df.sql
pg_restore --section=pre-data  --no-owner --no-privileges --no-tablespaces -f $O/rj_pre.raw.sql  $D/banco_rj.sql
pg_restore --section=post-data --no-owner --no-privileges                  -f $O/rj_post.raw.sql $D/banco_rj.sql
pg_restore --section=pre-data  --no-owner --no-privileges --no-tablespaces -n mapcartctrl -n mapcartsis -f $O/mc_pre.raw.sql  $D/banco_rj.sql
pg_restore --section=post-data --no-owner --no-privileges                  -n mapcartctrl -n mapcartsis -f $O/mc_post.raw.sql $D/banco_rj.sql
for f in df_pre df_post rj_pre rj_post mc_post; do python3 scripts/dev/adaptar_ddl.py $O/$f.raw.sql $O/$f.sql; done
python3 scripts/dev/adaptar_ddl.py $O/mc_pre.raw.sql $O/mc_pre.sql mapcartctrl,mapcartsis
scp $O/*_pre.sql $O/*_post.sql victor@disbelief:/home/victor/feixe-dumps/sql/
scp apoio/banco_df.sql apoio/banco_rj.sql scripts/dev/restaurar_dumps.sh victor@disbelief:/home/victor/feixe-dumps/
```

2. No disbelief, `FEIXE_DB_PASSWORD=... bash /home/victor/feixe-dumps/restaurar_dumps.sh`. O script aplica pre-data com `psql`, carrega os dados com o `pg_restore` 17 do container `feixe-ccar` (apontando para o `feixe-ggc` quando for o caso) e aplica post-data. O banco da GGC recebe também `mapcartctrl` e `mapcartsis` copiados do dump da CCAR, como em produção.

3. Erros esperados e inofensivos: triggers de histórico (`*_hist`), duas views de `mapcartctrl` que dependem de `ccar.*`, e `SET` de parâmetros do 17 que o 9.6 não conhece.

Resultado em 2026-10-08: GGC com 220 classes em `bc100ggcdf_base`, 41.436 cargas e 8.666 amostras em `bc100ggcdf_apoio`, 548 usuários e 3.049 folhas 1:100k em `mapcartctrl`; CCAR com 286 classes em `bc100grj_base`, 43 tabelas e 15 views em `mapcartctrl`, 64.831 folhas na articulação.
