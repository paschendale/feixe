#!/usr/bin/env bash
# Só para dev. A CCAR de dev não é a de produção e não tem as contas da GGC-DF em mapcartctrl.t_usuario, mas
# mapcartacomp.usuario_feixe (na CCAR) tem FK para lá. Este script copia do banco da GGC de dev para o da CCAR de dev
# as contas lotadas no DF e as que aparecem em bc100ggcdf_apoio (equipe e responsáveis), sem a senha, sem disparar os
# triggers de sincronização de t_usuario e sem sobrescrever conta que já exista.
#
# Uso: scripts/dev/copiar_usuarios_df.sh <conninfo_ggc> <conninfo_ccar>
set -euo pipefail
GGC="${1:?uso: copiar_usuarios_df.sh <conninfo_ggc> <conninfo_ccar>}"
CCAR="${2:?uso: copiar_usuarios_df.sh <conninfo_ggc> <conninfo_ccar>}"
COLS="nom_contausuario, num_siape, nom_usuario, nom_identificador_rede_ibge, dsc_ramal, ind_contaativa, ind_contasistema,
      ind_contasuper, dsc_lotacao, dsc_email, tag_observacao_ng"

psql "$GGC" -X -q -v ON_ERROR_STOP=1 -c "\copy (
    SELECT $COLS FROM mapcartctrl.t_usuario u
     WHERE upper(u.dsc_lotacao) LIKE 'DF%'
        OR u.nom_contausuario IN (SELECT usuario FROM bc100ggcdf_apoio.equipe)
        OR u.nom_contausuario IN (SELECT responsavel FROM bc100ggcdf_apoio.carga_trabalho)
) TO STDOUT WITH (FORMAT csv)" |
    psql "$CCAR" -X -q -v ON_ERROR_STOP=1 \
        -c "CREATE TEMP TABLE u_df AS SELECT $COLS FROM mapcartctrl.t_usuario LIMIT 0" \
        -c "\copy u_df FROM STDIN WITH (FORMAT csv)" \
        -c "SET session_replication_role = replica" \
        -c "INSERT INTO mapcartctrl.t_usuario ($COLS) SELECT $COLS FROM u_df ON CONFLICT DO NOTHING" \
        -c "SELECT count(*) AS no_dump, (SELECT count(*) FROM mapcartctrl.t_usuario t WHERE t.nom_contausuario IN
                (SELECT nom_contausuario FROM u_df)) AS na_ccar FROM u_df"
