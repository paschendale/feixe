# scripts/dev

Ferramentas do ambiente de desenvolvimento (stack `feixe-db` no host de dev: `feixe-ggc` PostgreSQL 9.6 + PostGIS 2.5 na porta 5433, o mais perto do PostGIS 2.4 do DF de produção e `feixe-ccar` PostgreSQL 17 + PostGIS 3.5 na porta 5434). Senha e URLs em `.dev.env` na raiz do repo (symlink para `~/.config/feixe/dev.env`, fora do Git).

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
scp $O/*_pre.sql $O/*_post.sql <host-dev>:feixe-dumps/sql/
scp apoio/banco_df.sql apoio/banco_rj.sql scripts/dev/restaurar_dumps.sh <host-dev>:feixe-dumps/
```

2. No host de dev, `FEIXE_DB_PASSWORD=... bash ~/feixe-dumps/restaurar_dumps.sh` (outra pasta: `FEIXE_DUMPS=...`). O script aplica pre-data com `psql`, carrega os dados com o `pg_restore` 17 do container `feixe-ccar` (apontando para o `feixe-ggc` quando for o caso) e aplica post-data. O banco da GGC recebe também `mapcartctrl` e `mapcartsis` copiados do dump da CCAR, como em produção.

3. Erros esperados e inofensivos: triggers de histórico (`*_hist`), duas views de `mapcartctrl` que dependem de `ccar.*`, e `SET` de parâmetros do 17 que o 9.6 não conhece.

Resultado em 2026-10-08: GGC com 220 classes em `bc100ggcdf_base`, 41.436 cargas e 8.666 amostras em `bc100ggcdf_apoio`, 548 usuários e 3.049 folhas 1:100k em `mapcartctrl`; CCAR com 286 classes em `bc100grj_base`, 43 tabelas e 15 views em `mapcartctrl`, 64.831 folhas na articulação.

## Atualizar só alguns schemas (recorte)

Para trazer um dump parcial mais novo (por exemplo `mapcartctrl`, `bc100ggcdf_apoio` e `dominios` da GGC-DF, ou `mapcartctrl`, `mapcartsis` e `dominios` da CCAR) sem refazer o resto:

1. Na sua máquina, gerar e adaptar as seções pre-data e post-data, mantendo as referências a `dominios` (que agora vem no dump):

```bash
O=/tmp/feixe-recorte; mkdir -p $O
pg_restore --section=pre-data  --no-owner --no-privileges --no-tablespaces -f $O/pre.raw.sql  apoio/<dump>
pg_restore --section=post-data --no-owner --no-privileges                  -f $O/post.raw.sql apoio/<dump>
for f in pre post; do python3 scripts/dev/adaptar_ddl.py $O/$f.raw.sql $O/$f.sql --com-dominios; done
scp apoio/<dump> $O/pre.sql $O/post.sql scripts/dev/restaurar_recorte.sh <host-dev>:feixe-dumps/recorte/
```

2. No host de dev, `FEIXE_DB_PASSWORD=... bash restaurar_recorte.sh <feixe-ggc|feixe-ccar> <dump> pre.sql post.sql <schema,...>`. Os schemas listados são removidos antes (inclua `mapcartacomp`, porque as FKs dele para `mapcartctrl` caem junto). Restaurar pela própria máquina pela rede funciona, mas o link é lento e já caiu no meio da carga; pelo host de dev é mais seguro.

3. Depois: `scripts/db/aplicar.sh` na CCAR de dev, `scripts/db/testar_espelho.sh` no GGC de dev e, como a CCAR de dev não é a de produção e não tem as contas do DF, `scripts/dev/copiar_usuarios_df.sh "$FEIXE_GGC" "$FEIXE_CCAR"` (copia as contas lotadas no DF e as citadas em `bc100ggcdf_apoio`, sem senha e sem disparar os triggers de sincronização).

Resultado em 2026-10-14: GGC com 45.009 cargas, 10.974 amostras e 19 ocorrências em `bc100ggcdf_apoio`, 456 contas em `mapcartctrl` e `dominios` com 183 tabelas; CCAR com 548 contas (mais 116 copiadas do DF), 64.831 folhas e `dominios` com 179 tabelas.

## Medir o pull (S-03)

`medir_pull.py` cronometra o pull inicial do workspace (C2) contra a CCAR de dev, em workspaces numa pasta temporária: (a) o escopo da pessoa com mais cargas no DF e (b) toda a `carga_trabalho` do DF, cada um seguido de um pull sem mudanças, separando o tempo de CCAR (consultas e rede) e o de gravação no workspace. Só lê o banco.

```bash
/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/medir_pull.py 3
```

Com o Python do QGIS ele usa as conexões do plugin e confere também a sincronização de ponta a ponta (CCAR de dev e uma porta fechada, que tem de dar `offline`). Sem o QGIS (só `psycopg2`), conecta pela URL `FEIXE_CCAR`; é o jeito de medir no host de dev, num container descartável com `python:3.9-slim` e `pip install psycopg2-binary`, com o código copiado por `rsync` (sem `.git` e sem `node_modules`).

## Verificar a fase C e testar o offline (C4)

`verificar_fase_c.py c4` reproduz o ciclo offline de ponta a ponta, sem abrir o QGIS e sem parar container nenhum: copia cinco cargas do DF para a conta de dev, prepara um workspace temporário com o pull, simula a CCAR inalcançável, monta as camadas do workspace (a Supervisão fica de fora, com aviso), conclui uma carga pela API e outra editando `concluido` na camada (edição + commit, com uma recusa e uma geometria mexida no mesmo commit), confere as duas no workspace e na outbox, confere que uma camada da mesma tabela sem o Feixe não consegue gravar, salva e reabre o projeto, devolve a CCAR, sincroniza e confere as duas concluídas na CCAR e no `sync_log`. Apaga o que criou.

```bash
/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3 scripts/dev/verificar_fase_c.py c4
```

CCAR fora do ar de mentira, só no ambiente de dev (o host do banco tem outros serviços: nunca pare o container para isso). O plugin trata a CCAR como inalcançável enquanto existir o arquivo `~/.feixe/dev/sem_ccar`, ou com `FEIXE_DEV_SEM_CCAR=1` no ambiente do QGIS. O arquivo dá para criar e apagar com o QGIS aberto: vale na próxima conexão (o teste de rede roda a cada minuto, e "Sincronizar agora" testa na hora). Em homologação e produção isso não existe: o nome do ambiente vem chumbado no build.

```bash
touch ~/.feixe/dev/sem_ccar   # a CCAR "cai"
rm ~/.feixe/dev/sem_ccar      # a CCAR "volta"
```
