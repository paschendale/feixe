import { useState } from 'react'
import { ChevronDown, ChevronRight, Plus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Bloco, CabecalhoModulo, Carregando, Colunas, Conteudo } from '@/components/painel'
import type { Atividade, Catalogo as TCatalogo, Tema } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { GERACAO, nivelGrade, plural } from '@/lib/formato'
import { href, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { FormAtividade } from '../atividades/FormAtividade'

function geraCargas(a: Atividade) {
  if (!a.geracao || a.geracao === 'nenhuma') return 'não'
  const g = GERACAO[a.geracao] ?? a.geracao
  return a.grade_nivel ? `${g.toLowerCase()}, ${nivelGrade(a.grade_nivel)}` : g
}

function uso(a: Atividade) {
  if (!a.ativo) return <Badge variant="outline">inativa</Badge>
  if (a.tem_cargas) return 'com cargas'
  if (a.em_uso) return 'em fluxo'
  return <span className="text-muted-foreground">sem uso</span>
}

function SecaoTema({ t, atividades, abrir, gerente, editar }: { t: Tema; atividades: Atividade[]; abrir: boolean; gerente: boolean; editar: (a: Atividade) => void }) {
  const [aberto, setAberto] = useState(abrir)
  const fases = [...new Set(atividades.map((a) => a.fase_nome))]
  return (
    <Bloco className="gap-0 p-0">
      <button type="button" aria-expanded={aberto} onClick={() => setAberto(!aberto)} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-5 py-4 text-left">
        {aberto ? <ChevronDown className="size-4 self-center" /> : <ChevronRight className="size-4 self-center" />}
        <h2 className="text-base font-semibold">{t.nome}</h2>
        {!t.ativo && <Badge variant="outline">inativo</Badge>}
        <span className="text-[13px] text-muted-foreground">
          {plural(atividades.length, 'atividade', 'atividades')}
          {fases.length ? ` · ${fases.join(', ').toLowerCase()}` : ''}
        </span>
      </button>
      {aberto && (
        <div className="overflow-x-auto border-t">
          {atividades.length === 0 ? (
            <p className="px-5 py-4 text-sm text-muted-foreground">Nenhuma atividade.</p>
          ) : (
            <table className="w-full min-w-[820px] table-fixed border-collapse text-sm">
              {/* Mesmas larguras em todos os temas: as colunas ficam alinhadas de um bloco para o outro. */}
              <Colunas larguras={[undefined, 150, 120, 210, 150, ...(gerente ? [110] : [])]} />
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="border-b py-2.5 pr-2 pl-5 font-medium">Atividade</th>
                  <th className="border-b px-2 py-2.5 font-medium">Fase</th>
                  <th className="border-b px-2 py-2.5 font-medium">Gera cargas</th>
                  <th className="border-b px-2 py-2.5 font-medium">Medida de qualidade</th>
                  <th className="border-b px-2 py-2.5 font-medium">Uso</th>
                  {gerente && <th className="border-b py-2.5 pr-5 pl-2" />}
                </tr>
              </thead>
              <tbody>
                {atividades.map((a) => (
                  <tr key={a.id} className={cn('border-b border-linha last:border-0', !a.ativo && 'text-muted-foreground')}>
                    <td className="py-2.5 pr-2 pl-5 font-medium">{a.nome}</td>
                    <td className="px-2 py-2.5">{a.fase_nome}</td>
                    <td className="px-2 py-2.5">{geraCargas(a)}</td>
                    <td className="px-2 py-2.5">{a.medida ?? '—'}</td>
                    <td className="px-2 py-2.5">{uso(a)}</td>
                    {gerente && (
                      <td className="py-2.5 pr-5 pl-2 text-right">
                        <Button size="sm" variant="outline" onClick={() => editar(a)}>
                          Editar
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Bloco>
  )
}

function Temas({ dados, gerente }: { dados: TCatalogo; gerente: boolean }) {
  const avisar = useAvisar()
  async function novoTema() {
    const nome = window.prompt('Nome do novo tema')
    if (!nome?.trim()) return
    try {
      await enviar('/api/temas', { nome })
      avisar(`Tema criado: ${nome.trim()}`)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }
  async function alternar(t: Tema) {
    try {
      await enviar(`/api/temas/${t.id}`, { ativo: !t.ativo }, 'PATCH')
      avisar(`${t.nome}: ${t.ativo ? 'desativado' : 'ativado'}`)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }
  return (
    <>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="max-w-[760px] text-[13px] text-muted-foreground">Temas agrupam as atividades e os fluxos (hidrografia, áreas densamente edificadas, LML…). Cada folha é de um tema.</p>
        {gerente && (
          <Button onClick={novoTema}>
            <Plus /> Novo tema
          </Button>
        )}
      </div>
      <div className="overflow-x-auto rounded-[10px] border bg-card">
        <table className="w-full table-fixed border-collapse text-sm">
          <Colunas larguras={[undefined, 120, 160, ...(gerente ? [110] : [])]} />
          <thead>
            <tr className="text-left text-xs text-muted-foreground">
              <th className="border-b py-2.5 pr-2 pl-5 font-medium">Tema</th>
              <th className="border-b px-2 py-2.5 text-right font-medium">Atividades</th>
              <th className="border-b px-2 py-2.5 font-medium">Situação</th>
              {gerente && <th className="border-b py-2.5 pr-5 pl-2" />}
            </tr>
          </thead>
          <tbody>
            {dados.temas.map((t) => (
              <tr key={t.id} className="border-b border-linha last:border-0">
                <td className="py-2.5 pr-2 pl-5 font-medium">{t.nome}</td>
                <td className="tab px-2 py-2.5 text-right">{t.atividades}</td>
                <td className="px-2 py-2.5">{t.ativo ? 'ativo' : <Badge variant="outline">inativo</Badge>}</td>
                {gerente && (
                  <td className="py-2.5 pr-5 pl-2 text-right">
                    <Button size="sm" variant="ghost" onClick={() => alternar(t)}>
                      {t.ativo ? 'Desativar' : 'Ativar'}
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

// Catálogo nacional (B7), mantido pela CCAR: todos veem; só o gerente cria e altera (D-87).
export default function Catalogo() {
  const { tem } = useSessao()
  const rota = useRota()
  const gerente = tem('gerente')
  const { dados, erro } = useApi<TCatalogo>('/api/catalogo', ['atividade'])
  const [form, setForm] = useState<{ atividade: Atividade | null } | null>(null)
  const aba = rota.partes[0] === 'temas' ? 'temas' : 'atividades'
  return (
    <>
      <CabecalhoModulo
        titulo="Catálogo"
        sub={`nacional, mantido pela CCAR${gerente ? '' : ' · só leitura'}`}
        ativa={aba}
        abas={[
          { id: 'atividades', rotulo: 'Atividades', href: href('catalogo/atividades') },
          { id: 'temas', rotulo: 'Temas', href: href('catalogo/temas') },
          { id: 'elementos', rotulo: 'Elementos de CQ · fase D', desabilitada: true },
        ]}
      />
      <Conteudo largura={1240}>
        {!dados && <Carregando erro={erro} />}
        {dados && aba === 'temas' && <Temas dados={dados} gerente={gerente} />}
        {dados && aba === 'atividades' && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="max-w-[820px] text-[13px] text-muted-foreground">
                As unidades montam os fluxos com estas atividades: cada uma é projeto + tema + fase, com o jeito de gerar as cargas. Supervisores e APMs veem o catálogo; só o gerente cria e altera. Atividade em uso não muda de nível da grade, e não se desativa enquanto estiver num fluxo ativo.
              </p>
              {gerente && (
                <Button onClick={() => setForm({ atividade: null })}>
                  <Plus /> Nova atividade
                </Button>
              )}
            </div>
            {dados.temas.map((t, i) => (
              <SecaoTema key={t.id} t={t} atividades={dados.atividades.filter((a) => a.id_tema === t.id)} abrir={i === 0} gerente={gerente} editar={(a) => setForm({ atividade: a })} />
            ))}
            {gerente && <FormAtividade catalogo={dados} atividade={form?.atividade ?? null} aberto={!!form} fechar={() => setForm(null)} />}
          </>
        )}
      </Conteudo>
    </>
  )
}
