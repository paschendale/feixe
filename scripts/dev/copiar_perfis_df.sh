#!/usr/bin/env bash
# Só para dev. A CCAR de dev não é a de produção e não tem os perfis do SGBC das contas do DF; a de produção tem (D-82).
# Este script copia do banco da GGC de dev para o da CCAR de dev os perfis (projeto + perfil) das contas lotadas no DF
# que existem nos dois, casando conta pelo nome e projeto pelo nome, sem disparar a sincronização com as GGCs.
#
# Uso: scripts/dev/copiar_perfis_df.sh <conninfo_ggc> <conninfo_ccar>
set -euo pipefail
GGC="${1:?uso: copiar_perfis_df.sh <conninfo_ggc> <conninfo_ccar>}"
CCAR="${2:?uso: copiar_perfis_df.sh <conninfo_ggc> <conninfo_ccar>}"

psql "$GGC" -X -q -v ON_ERROR_STOP=1 -c "\copy (
    SELECT u.nom_contausuario, pr.nom_projeto, p.cd_perfil FROM mapcartctrl.t_prd_perfil_usuarioprojeto p
      JOIN mapcartctrl.t_usuario u ON u.cod_usuario = p.cd_usuario
      JOIN mapcartctrl.t_projeto pr ON pr.cod_projeto = p.cd_projeto
     WHERE upper(trim(u.dsc_lotacao)) = 'DF'
) TO STDOUT WITH (FORMAT csv)" |
    psql "$CCAR" -X -q -v ON_ERROR_STOP=1 \
        -c "CREATE TEMP TABLE perfis (conta text, projeto text, perfil char(1))" \
        -c "\copy perfis FROM STDIN WITH (FORMAT csv)" \
        -c "SET session_replication_role = replica" \
        -c "INSERT INTO mapcartctrl.t_prd_perfil_usuarioprojeto (cd_usuario, cd_projeto, cd_perfil)
            SELECT u.cod_usuario, pr.cod_projeto, p.perfil FROM perfis p
              JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = p.conta
              JOIN mapcartctrl.t_projeto pr ON pr.nom_projeto = p.projeto
            ON CONFLICT (cd_usuario, cd_projeto) DO UPDATE SET cd_perfil = EXCLUDED.cd_perfil" \
        -c "SELECT count(*) AS perfis_no_dump, (SELECT count(*) FROM mapcartctrl.t_prd_perfil_usuarioprojeto p
              JOIN mapcartctrl.t_usuario u ON u.cod_usuario = p.cd_usuario
             WHERE upper(trim(u.dsc_lotacao)) = 'DF') AS perfis_df_na_ccar FROM perfis"
