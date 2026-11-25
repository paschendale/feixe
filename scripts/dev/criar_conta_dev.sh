#!/usr/bin/env bash
# Só para dev. Cria na CCAR de dev uma role de login para uma conta real do SGBC, para testar o plugin como aquela
# pessoa (papel, UF, cargas). Em homologação e produção nada disso existe: a conta e os GRANTs são da DBA.
#
# - role de login com a senha dada (ALTER se já existir), membro do grupo de dev feixe_dev_usuarios;
# - o grupo recebe os GRANTs do Feixe (gerar_grants.py) e leitura em mapcartctrl, como as roles reais da CCAR;
# - os perfis da conta no SGBC são copiados do banco da GGC de dev para a CCAR de dev (a CCAR de dev não é a de
#   produção e não tem esses perfis), casando projeto pelo nome e sem disparar a sincronização com as GGCs.
#
# A conta precisa existir em mapcartctrl.t_usuario da CCAR de dev (scripts/dev/copiar_usuarios_df.sh).
# Uso: scripts/dev/criar_conta_dev.sh <conninfo_ggc> <conninfo_ccar> <conta> <senha>
set -euo pipefail
GGC="${1:?uso: criar_conta_dev.sh <conninfo_ggc> <conninfo_ccar> <conta> <senha>}"
CCAR="${2:?}"
CONTA="${3:?}"
SENHA="${4:?}"
[[ "$CONTA" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "conta inválida: $CONTA" >&2; exit 1; }
RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

psql "$CCAR" -X -q -v ON_ERROR_STOP=1 -v conta="$CONTA" -v senha="$SENHA" <<'SQL'
SELECT EXISTS (SELECT 1 FROM mapcartctrl.t_usuario WHERE nom_contausuario = :'conta') AS existe \gset
\if :existe
\else
\echo 'conta ausente de mapcartctrl.t_usuario na CCAR de dev (rode copiar_usuarios_df.sh)'
\quit 1
\endif
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'feixe_dev_usuarios') THEN
        CREATE ROLE feixe_dev_usuarios NOLOGIN;
    END IF;
END $$;
SELECT format('CREATE ROLE %I LOGIN', :'conta') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'conta') \gexec
SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'conta', :'senha') \gexec
SELECT format('GRANT feixe_dev_usuarios TO %I', :'conta') \gexec
GRANT USAGE ON SCHEMA mapcartctrl TO feixe_dev_usuarios;
GRANT SELECT ON ALL TABLES IN SCHEMA mapcartctrl TO feixe_dev_usuarios;
SQL

echo feixe_dev_usuarios | python3 "$RAIZ/scripts/db/gerar_grants.py" --roles - | psql "$CCAR" -X -q -v ON_ERROR_STOP=1

psql "$GGC" -X -q -v ON_ERROR_STOP=1 -v conta="$CONTA" -c "\copy (
    SELECT pr.nom_projeto, p.cd_perfil FROM mapcartctrl.t_prd_perfil_usuarioprojeto p
      JOIN mapcartctrl.t_projeto pr ON pr.cod_projeto = p.cd_projeto
      JOIN mapcartctrl.t_usuario u ON u.cod_usuario = p.cd_usuario
     WHERE u.nom_contausuario = '$CONTA'
) TO STDOUT WITH (FORMAT csv)" |
    psql "$CCAR" -X -q -v ON_ERROR_STOP=1 \
        -c "CREATE TEMP TABLE perfis (projeto text, perfil char(1))" \
        -c "\copy perfis FROM STDIN WITH (FORMAT csv)" \
        -c "SET session_replication_role = replica" \
        -c "INSERT INTO mapcartctrl.t_prd_perfil_usuarioprojeto (cd_usuario, cd_projeto, cd_perfil)
            SELECT u.cod_usuario, pr.cod_projeto, p.perfil FROM perfis p
              JOIN mapcartctrl.t_projeto pr ON pr.nom_projeto = p.projeto
              JOIN mapcartctrl.t_usuario u ON u.nom_contausuario = '$CONTA'
            ON CONFLICT (cd_usuario, cd_projeto) DO UPDATE SET cd_perfil = EXCLUDED.cd_perfil"

echo "conta $CONTA pronta na CCAR de dev"
