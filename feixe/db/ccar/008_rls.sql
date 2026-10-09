-- 008: row level security por UF com as roles que a CCAR já tem. Compatível com PostgreSQL 9.6. Idempotente.
--
-- Nenhuma role é criada aqui. A UF de quem consulta vem das roles de grupo de que ele é membro, pela convenção
-- role_<projeto><unidade>_atua / _sup, em que a unidade termina na sigla da UF (role_bc100ggcdf_atua -> DF,
-- role_bc100grj_sup -> RJ). A convenção está só em f_ufs(); se a lista real de roles (P-21) pedir outra, muda ali.
--
-- Os GRANTs (o que cada role pode fazer em cada tabela e coluna) são gerados para as roles reais por
-- scripts/db/gerar_grants.py. Aqui ficam as políticas (quais linhas). O dono das tabelas não passa por RLS.
--
-- Visibilidade: membro de _atua ou _sup de uma UF vê as linhas daquela UF; o gerente (usuario_feixe.gerente) vê
-- todas. Escrita de planejamento (lotes, etapas, cargas, planos, fluxos, calendário): só _sup da UF. Quem executa
-- (_atua) conclui as próprias cargas, avalia as próprias amostras e registra e trata ocorrências.

-- UFs em que o usuário corrente é membro de alguma role do papel pedido ('atua', 'sup').
-- Sem SECURITY DEFINER de propósito: dentro dele current_user seria o dono da função, não quem consulta.
CREATE OR REPLACE FUNCTION mapcartacomp.f_ufs(p_papeis text[]) RETURNS text[]
LANGUAGE sql STABLE AS $$
    SELECT coalesce(array_agg(DISTINCT upper(substring(r.rolname FROM '([a-z]{2})_(?:atua|sup)$'))), '{}')
      FROM pg_catalog.pg_roles r
     WHERE r.rolname ~ '^role_[a-z0-9_]+_(atua|sup)$'
       AND substring(r.rolname FROM '_(atua|sup)$') = ANY (p_papeis)
       AND pg_catalog.pg_has_role(current_user, r.oid, 'MEMBER')
$$;

CREATE OR REPLACE FUNCTION mapcartacomp.f_gerente() RETURNS boolean
LANGUAGE sql STABLE AS $$
    SELECT EXISTS (SELECT 1 FROM mapcartacomp.usuario_feixe WHERE usuario = current_user AND gerente AND ativo)
$$;

-- As derivações escrevem em tabelas que quem as dispara pode não poder alterar (o avaliador avalia a amostra e o
-- plano é recalculado; o supervisor muda a etapa e o lote é recalculado). Rodam com os direitos do dono do schema.
ALTER FUNCTION mapcartacomp.f_amostra_derivar_um(integer, integer)
    SECURITY DEFINER SET search_path = mapcartacomp, public, pg_temp;
ALTER FUNCTION mapcartacomp.f_lote_derivar(integer)
    SECURITY DEFINER SET search_path = mapcartacomp, public, pg_temp;

-- Políticas. Os (SELECT f(...)) viram InitPlan: avaliados uma vez por consulta, não por linha.
DO $$
DECLARE
    t text;
    ver constant text := '((SELECT mapcartacomp.f_gerente()) OR uf::text = ANY ((SELECT mapcartacomp.f_ufs(''{atua,sup}''))::text[]))';
    sup constant text := '(uf::text = ANY ((SELECT mapcartacomp.f_ufs(''{sup}''))::text[]))';
BEGIN
    FOREACH t IN ARRAY ARRAY['lote', 'lote_etapa', 'lote_etapa_hist', 'carga_trabalho', 'cq_plano', 'cq_amostra',
                             'cq_inspecao', 'fluxo', 'fluxo_etapa', 'calendario', 'usuario_feixe', 'sync_log']
    LOOP
        EXECUTE format('ALTER TABLE mapcartacomp.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS p_ler ON mapcartacomp.%I', t);
        EXECUTE format('DROP POLICY IF EXISTS p_inserir ON mapcartacomp.%I', t);
        EXECUTE format('DROP POLICY IF EXISTS p_alterar ON mapcartacomp.%I', t);
        EXECUTE format('DROP POLICY IF EXISTS p_excluir ON mapcartacomp.%I', t);
    END LOOP;

    -- Planejamento: lê quem é da UF, escreve o supervisor da UF.
    FOREACH t IN ARRAY ARRAY['lote', 'lote_etapa', 'lote_etapa_hist', 'cq_plano', 'calendario']
    LOOP
        EXECUTE format('CREATE POLICY p_ler ON mapcartacomp.%I FOR SELECT USING %s', t, ver);
        EXECUTE format('CREATE POLICY p_inserir ON mapcartacomp.%I FOR INSERT WITH CHECK %s', t, sup);
        EXECUTE format('CREATE POLICY p_alterar ON mapcartacomp.%I FOR UPDATE USING %s WITH CHECK %s', t, sup, sup);
        EXECUTE format('CREATE POLICY p_excluir ON mapcartacomp.%I FOR DELETE USING %s', t, sup);
    END LOOP;

    -- Fluxos: todos leem (para copiar o fluxo de outra UF); escreve o supervisor da UF do fluxo.
    EXECUTE 'CREATE POLICY p_ler ON mapcartacomp.fluxo FOR SELECT USING (true)';
    EXECUTE format('CREATE POLICY p_inserir ON mapcartacomp.fluxo FOR INSERT WITH CHECK %s', sup);
    EXECUTE format('CREATE POLICY p_alterar ON mapcartacomp.fluxo FOR UPDATE USING %s WITH CHECK %s', sup, sup);
    EXECUTE format('CREATE POLICY p_excluir ON mapcartacomp.fluxo FOR DELETE USING %s', sup);
    EXECUTE 'CREATE POLICY p_ler ON mapcartacomp.fluxo_etapa FOR SELECT USING (true)';
    t := '(EXISTS (SELECT 1 FROM mapcartacomp.fluxo f WHERE f.id = id_fluxo AND f.uf::text = ANY '
         '((SELECT mapcartacomp.f_ufs(''{sup}''))::text[])))';
    EXECUTE format('CREATE POLICY p_inserir ON mapcartacomp.fluxo_etapa FOR INSERT WITH CHECK %s', t);
    EXECUTE format('CREATE POLICY p_alterar ON mapcartacomp.fluxo_etapa FOR UPDATE USING %s WITH CHECK %s', t, t);
    EXECUTE format('CREATE POLICY p_excluir ON mapcartacomp.fluxo_etapa FOR DELETE USING %s', t);

    -- Cargas: o supervisor faz tudo na UF; o responsável altera a própria carga (as colunas vêm dos GRANTs).
    EXECUTE format('CREATE POLICY p_ler ON mapcartacomp.carga_trabalho FOR SELECT USING %s', ver);
    EXECUTE format('CREATE POLICY p_inserir ON mapcartacomp.carga_trabalho FOR INSERT WITH CHECK %s', sup);
    EXECUTE format('CREATE POLICY p_alterar ON mapcartacomp.carga_trabalho FOR UPDATE '
                   'USING (%1$s OR (responsavel = current_user AND %2$s)) '
                   'WITH CHECK (%1$s OR (responsavel = current_user AND %2$s))', sup, ver);
    EXECUTE format('CREATE POLICY p_excluir ON mapcartacomp.carga_trabalho FOR DELETE USING %s', sup);

    -- Amostras: o supervisor faz tudo na UF; o avaliador altera as amostras das cargas de CQ que são dele.
    t := '(EXISTS (SELECT 1 FROM mapcartacomp.carga_trabalho c WHERE c.id = id_carga_trabalho '
         'AND c.responsavel = current_user))';
    EXECUTE format('CREATE POLICY p_ler ON mapcartacomp.cq_amostra FOR SELECT USING %s', ver);
    EXECUTE format('CREATE POLICY p_inserir ON mapcartacomp.cq_amostra FOR INSERT WITH CHECK %s', sup);
    EXECUTE format('CREATE POLICY p_alterar ON mapcartacomp.cq_amostra FOR UPDATE '
                   'USING (%1$s OR (%2$s AND %3$s)) WITH CHECK (%1$s OR (%2$s AND %3$s))', sup, t, ver);
    EXECUTE format('CREATE POLICY p_excluir ON mapcartacomp.cq_amostra FOR DELETE USING %s', sup);

    -- Ocorrências: quem é da UF registra as suas e marca qualquer uma como tratada (correção de inspeção);
    -- só o autor ou o supervisor exclui.
    EXECUTE format('CREATE POLICY p_ler ON mapcartacomp.cq_inspecao FOR SELECT USING %s', ver);
    EXECUTE format('CREATE POLICY p_inserir ON mapcartacomp.cq_inspecao FOR INSERT '
                   'WITH CHECK (%1$s OR (responsavel = current_user AND %2$s))', sup, ver);
    EXECUTE format('CREATE POLICY p_alterar ON mapcartacomp.cq_inspecao FOR UPDATE USING %1$s WITH CHECK %1$s', ver);
    EXECUTE format('CREATE POLICY p_excluir ON mapcartacomp.cq_inspecao FOR DELETE '
                   'USING (%s OR (responsavel = current_user AND %s))', sup, ver);

    -- Usuários do Feixe: todos leem; o supervisor da UF de lotação do usuário mantém equipe e papel.
    t := '(EXISTS (SELECT 1 FROM mapcartctrl.t_usuario u WHERE u.nom_contausuario = usuario '
         'AND upper(u.dsc_lotacao) = ANY ((SELECT mapcartacomp.f_ufs(''{sup}''))::text[])))';
    EXECUTE 'CREATE POLICY p_ler ON mapcartacomp.usuario_feixe FOR SELECT USING (true)';
    EXECUTE format('CREATE POLICY p_inserir ON mapcartacomp.usuario_feixe FOR INSERT WITH CHECK %s', t);
    EXECUTE format('CREATE POLICY p_alterar ON mapcartacomp.usuario_feixe FOR UPDATE USING %s WITH CHECK %s', t, t);
    EXECUTE format('CREATE POLICY p_excluir ON mapcartacomp.usuario_feixe FOR DELETE USING %s', t);

    -- Registro de sincronização: cada um grava o seu; lê o seu, o supervisor da UF e o gerente.
    EXECUTE 'CREATE POLICY p_inserir ON mapcartacomp.sync_log FOR INSERT WITH CHECK (usuario = current_user)';
    EXECUTE format('CREATE POLICY p_ler ON mapcartacomp.sync_log FOR SELECT '
                   'USING (usuario = current_user OR (SELECT mapcartacomp.f_gerente()) OR %s)', sup);
END
$$;
