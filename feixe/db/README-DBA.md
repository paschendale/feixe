# Pacote de banco do Feixe

Este diretório tem tudo o que precisa ser aplicado nos bancos para o Feixe funcionar: o schema `mapcartacomp` no banco da CCAR (onde ficam os dados, a única cópia autoritativa) e, opcionalmente, um espelho somente leitura em cada GGC. Os scripts estão prontos; nada precisa ser desenhado. O plugin escreve só no banco da CCAR e nunca no banco das GGCs.

```mermaid
flowchart LR
  subgraph ccar["Banco da CCAR (PostgreSQL 17)"]
    c1["ccar/001 a 008<br/>schema, tabelas, regras, views, RLS"] --> c2["GRANTs gerados<br/>para as roles existentes"]
  end
  subgraph ggc["Banco de cada GGC (PostgreSQL 9.6), opcional"]
    g1["ggc/001_server_*<br/>servidor e mapeamento"] --> g2["ggc/002_foreign_tables_*<br/>espelho somente leitura"] --> g3["ggc/003_views_compat"] --> g4["GRANTs --espelho"]
  end
  c2 --> g1
```

## Conteúdo

| Arquivo | O que faz |
|---|---|
| `ccar/001_schema.sql` | Schema `mapcartacomp` e `schema_version` (controle das migrações) |
| `ccar/002_referencias.sql` | Tema, fase (com carga inicial), atividade, fluxo e etapas, usuários do Feixe, calendário |
| `ccar/003_lotes.sql` | Lotes (folhas e lotes livres), passagens por etapa, histórico, cargas de trabalho |
| `ccar/004_cq.sql` | Planos de amostragem, amostras e ocorrências de inspeção |
| `ccar/005_sync_log.sql` | Registro da sincronização |
| `ccar/006_regras.sql` | Triggers: datas de conclusão e avaliação, auditoria, derivação do status nacional |
| `ccar/007_views.sql` | Views de compatibilidade (`vw_*`, filtradas pelo usuário) e de acompanhamento (`ctrl_*`) |
| `ccar/008_rls.sql` | Row level security por UF |
| `ggc/001_server_fdw.sql` ou `ggc/001_server_dblink.sql` | Servidor remoto para a CCAR e mapeamento de usuário |
| `ggc/002_foreign_tables_fdw.sql` ou `ggc/002_foreign_tables_dblink.sql` | Tabelas da CCAR vistas na GGC, somente leitura |
| `ggc/003_views_compat.sql` | Views `vw_*` no banco da GGC, filtradas pelo usuário conectado na GGC |
| `ggc/remover.sql` | Remove o espelho de uma GGC |

Scripts auxiliares (na raiz do repositório): `scripts/db/aplicar.sh` (aplica as migrações que faltam), `scripts/db/gerar_grants.py` (gera os GRANTs para as roles reais) e `scripts/db/testar_espelho.sh` (confere o espelho).

## Pré-requisitos

- Banco da CCAR com PostGIS e o schema `mapcartctrl` (o Feixe referencia `t_projeto`, `t_articulacao_scn` e `t_usuario`, sem copiá-los).
- Definir a role dona do schema `mapcartacomp` (a mesma role administrativa dos schemas `*_apoio`). Ela precisa de `REFERENCES` em `mapcartctrl.t_projeto`, `mapcartctrl.t_articulacao_scn` e `mapcartctrl.t_usuario` e é quem aplica as migrações. O dono não passa pelas políticas de RLS.
- Lista das roles de grupo existentes (`role_<projeto><unidade>_atua` e `_sup`). Nenhuma role nova é criada pelo Feixe.
- Nas GGCs, para o espelho: extensão `postgres_fdw` (recomendada) ou `dblink`, e a conta que a GGC já usa para falar com a CCAR.
- Cliente `psql` (qualquer versão a partir da 9.6) e `bash`; o gerador de GRANTs usa só Python 3 sem pacotes extras.

## 1. Banco da CCAR

1. Criar o schema, se ainda não existir, já com o dono definido: `CREATE SCHEMA mapcartacomp AUTHORIZATION <role_dona>;` (o `001` usa `IF NOT EXISTS` e não recria).
2. Aplicar as migrações, conectado como a role dona:

   ```bash
   scripts/db/aplicar.sh "host=<host> port=<porta> dbname=<banco> user=<role_dona>"
   ```

   O script lê a versão atual em `mapcartacomp.schema_version`, aplica só as migrações que faltam, todas numa transação (entram todas ou nenhuma), e registra cada uma. Rodar de novo sem migrações novas não faz nada. Para conferir antes sem mudar nada, use `--ensaio`: aplica tudo do zero numa transação e desfaz no fim. Sem o script, aplicar com `psql -1 -v ON_ERROR_STOP=1 -f` cada arquivo em ordem e inserir a linha correspondente em `schema_version (versao, nome)`.
3. Gerar e aplicar os GRANTs para as roles reais:

   ```bash
   psql "<conexão>" -At -c "SELECT rolname FROM pg_roles WHERE rolname ~ '^role_.+_(atua|sup)$' ORDER BY 1" > roles.txt
   python3 scripts/db/gerar_grants.py --roles roles.txt > grants.sql
   psql "<conexão>" -v ON_ERROR_STOP=1 -f grants.sql
   ```

   Reaplicar quando surgir uma role nova (projeto ou GGC nova). GRANT repetido não tem efeito.

### O que cada role pode fazer

As políticas de RLS (`008_rls.sql`) decidem quais linhas; os GRANTs decidem quais tabelas e colunas.

| Quem | Vê | Altera |
|---|---|---|
| Membro de `_atua` da UF | Linhas da própria UF | Conclui as próprias cargas, avalia as amostras das próprias cargas de CQ, registra ocorrências e marca ocorrências como tratadas; exclui só as ocorrências que registrou |
| Membro de `_sup` da UF | Linhas da própria UF | Tudo de planejamento na própria UF: lotes, etapas, cargas, planos, fluxos, calendário, equipe dos usuários lotados na UF |
| Gerente (marcado em `mapcartacomp.usuario_feixe`, membro de alguma `_atua`) | Todas as UFs | O mesmo que a sua role |

A UF de quem consulta vem das roles de que ele é membro: a sigla é o fim do nome da unidade (`role_bc100ggcdf_atua` dá DF, `role_bc100grj_sup` dá RJ). Se a convenção real de nomes for outra, ela está isolada na função `mapcartacomp.f_ufs`.

As views `vw_*` filtram pelo usuário conectado e são editáveis (por RULE): quem continuar operando direto no QGIS conclui cargas e avalia amostras por elas, como hoje no `*_apoio`. Inserir ocorrência pela `vw_cq_inspecao` exige o campo `uuid` preenchido (no QGIS, valor padrão `uuid()`); o banco nunca gera uuid.

## 2. Espelho nas GGCs (opcional)

O espelho deixa as tabelas do Feixe visíveis no banco da própria GGC, para consultas SQL e camadas no QGIS, sem risco de escrita. O plugin não depende dele. Escolha uma variante: `postgres_fdw` (recomendada: os filtros são executados na CCAR) ou `dblink` (o mecanismo que o IBGE já usa; cada consulta traz a tabela inteira).

```bash
V=fdw   # ou dblink
psql "<conexão da GGC>" -v ON_ERROR_STOP=1 \
     -v ccar_host=<host da CCAR visto da GGC> -v ccar_porta=<porta> -v ccar_banco=<banco> \
     -v conta=<conta usada pela GGC> -v senha=<senha> \
     -f feixe/db/ggc/001_server_$V.sql
psql "<conexão da GGC>" -v ON_ERROR_STOP=1 -f feixe/db/ggc/002_foreign_tables_$V.sql
psql "<conexão da GGC>" -v ON_ERROR_STOP=1 -f feixe/db/ggc/003_views_compat.sql
python3 scripts/db/gerar_grants.py --roles roles_da_ggc.txt --espelho | psql "<conexão da GGC>" -v ON_ERROR_STOP=1
```

- O espelho vê o que a `conta` vê na CCAR: ela deve ser membro da role `_atua` da própria GGC, para enxergar a UF da GGC.
- A senha vai só para o mapeamento de usuário no catálogo do banco da GGC, como nos mapeamentos que já existem; não é gravada em arquivo.
- Somente leitura: na variante `postgres_fdw` o servidor é criado com `updatable 'false'`; na `dblink` as tabelas são views sobre `dblink()`. Os GRANTs `--espelho` são só `SELECT`.
- Depois de cada migração nova na CCAR, reaplicar `002` e `003` na GGC (eles removem e recriam o espelho com as colunas novas).
- Não aplique as migrações de `ccar/` no banco da GGC: lá o `mapcartacomp` é o espelho. A compatibilidade das migrações com o 9.6 é verificada com `aplicar.sh --ensaio`, que desfaz tudo.

## Rollback

- Espelho de uma GGC: `psql "<conexão da GGC>" -f feixe/db/ggc/remover.sql` (remove o schema do espelho e os servidores; não mexe nas extensões nem em dado nenhum).
- Banco da CCAR antes de ter dados de produção: `DROP SCHEMA mapcartacomp CASCADE;` volta ao estado anterior (nada fora do schema é alterado pelas migrações, exceto os GRANTs nas roles, que somem com o schema).
- Banco da CCAR com dados: as migrações só acrescentam; voltar uma migração é restaurar o backup feito antes de aplicá-la. Faça `pg_dump -n mapcartacomp` antes de cada atualização.

## Checklist de validação (homologação e produção)

1. `SELECT max(versao) FROM mapcartacomp.schema_version;` devolve a versão esperada pela release do plugin.
2. `SELECT codigo, status_nacional FROM mapcartacomp.fase ORDER BY ordem;` devolve as 7 fases.
3. `SELECT relname, relrowsecurity FROM pg_class WHERE relnamespace = 'mapcartacomp'::regnamespace AND relkind = 'r' ORDER BY 1;`: RLS ligado em todas as tabelas, exceto `schema_version`, `tema`, `fase` e `atividade`.
4. Conectado como um membro de `_atua` de uma UF: `SELECT DISTINCT uf FROM mapcartacomp.lote;` devolve só a UF dele; `INSERT` em `mapcartacomp.lote` é recusado.
5. Conectado como um membro de `_sup`: consegue criar um lote livre de teste na própria UF (e removê-lo); na UF de outra GGC, é recusado.
6. No plugin, o diálogo de usuário e senha conecta e o painel abre sem aviso de versão de schema.
7. Em cada GGC com espelho: `scripts/db/testar_espelho.sh "<conexão da GGC>" "<conexão da CCAR>" fdw` (com `ESPELHO_HOST`, `ESPELHO_PORTA`, `ESPELHO_BANCO`, `ESPELHO_CONTA` e `ESPELHO_SENHA` no ambiente) mostra as contagens iguais e a escrita recusada. Em produção, rodar com a conta do espelho, para que as contagens da CCAR sejam as da UF.
