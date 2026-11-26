import { useState } from 'react'
import { ChevronDown, ChevronRight, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Bloco, CabecalhoModulo, Carregando, Colunas, Conteudo, Selo, Tabela } from '@/components/ds'
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
  if (!a.ativo) return <Selo>inativa</Selo>
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
        <h2 className="text-titulo-3 font-semibold">{t.nome}</h2>
        {!t.ativo && <Selo className="self-center">inativo</Selo>}
        <span className="text-nota text-muted-foreground">
          {plural(atividades.length, 'atividade', 'atividades')}
          {fases.length ? ` · ${fases.join(', ').toLowerCase()}` : ''}
        </span>
      </button>
      {aberto && (
        <div className="border-t border-linha">
          {atividades.length === 0 ? (
            <p className="px-5 py-4 text-muted-foreground">Nenhuma atividade.</p>
          ) : (
            <Tabela solta fixa largura={820} className="px-5">
              {/* Mesmas larguras em todos os temas: as colunas ficam alinhadas de um bloco para o outro. */}
              <Colunas larguras={[undefined, 150, 120, 210, 150, ...(gerente ? [110] : [])]} />
              <thead>
                <tr>
                  <th>Atividade</th>
                  <th>Fase</th>
                  <th>Gera cargas</th>
                  <th>Medida de qualidade</th>
                  <th>Uso</th>
                  {gerente && <th />}
                </tr>
              </thead>
              <tbody>
                {atividades.map((a) => (
                  <tr key={a.id} className={cn(!a.ativo && 'text-muted-foreground')}>
                    <td className="font-medium">{a.nome}</td>
                    <td>{a.fase_nome}</td>
                    <td>{geraCargas(a)}</td>
                    <td>{a.medida ?? '—'}</td>
                    <td>{uso(a)}</td>
                    {gerente && (
                      <td className="text-right">
                        <Button size="sm" variant="outline" onClick={() => editar(a)}>
                          Editar
                        </Button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </Tabela>
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
        <p className="max-w-[760px] text-nota text-muted-foreground">Temas agrupam as atividades e os fluxos (hidrografia, áreas densamente edificadas, LML…). Cada folha é de um tema.</p>
        {gerente && (
          <Button onClick={novoTema}>
            <Plus /> Novo tema
          </Button>
        )}
      </div>
      <Tabela fixa>
          <Colunas larguras={[undefined, 120, 160, ...(gerente ? [110] : [])]} />
          <thead>
            <tr>
              <th>Tema</th>
              <th className="text-right">Atividades</th>
              <th>Situação</th>
              {gerente && <th />}
            </tr>
          </thead>
          <tbody>
            {dados.temas.map((t) => (
              <tr key={t.id}>
                <td className="font-medium">{t.nome}</td>
                <td className="tab text-right">{t.atividades}</td>
                <td>{t.ativo ? 'ativo' : <Selo>inativo</Selo>}</td>
                {gerente && (
                  <td className="text-right">
                    <Button size="sm" variant="ghost" onClick={() => alternar(t)}>
                      {t.ativo ? 'Desativar' : 'Ativar'}
                    </Button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
      </Tabela>
    </>
  )
}

// Elementos de qualidade do CQ (D-152): o catálogo da GCQ que as atividades de CQ usam, uma atividade por elemento.
// Só leitura em todos os papéis: na v0 o catálogo muda por SQL (seed do A8). O nome vem do SGBC.
function Elementos({ dados }: { dados: TCatalogo }) {
  const usos = (id: number) => dados.atividades.filter((a) => a.id_medidadequalidade === id)
  const fracao = (x: number) => `${Number(x).toLocaleString('pt-BR')}%`
  return (
    <>
      <p className="max-w-[820px] text-nota text-muted-foreground">
        Os elementos de qualidade que o CQ inspeciona, no vocabulário da GCQ. Cada atividade de CQ do catálogo mede um elemento, e o plano de amostragem de cada folha usa a fração crítica do elemento quando a etapa do fluxo não define outra. Mantidos pela CCAR; aqui, só leitura.
      </p>
      <Tabela fixa>
        <Colunas larguras={[undefined, 130, 150, 260, 110]} />
        <thead>
          <tr>
            <th>Elemento</th>
            <th>Núcleo da GCQ</th>
            <th className="text-right">Fração crítica padrão</th>
            <th>Atividades de CQ</th>
            <th>Situação</th>
          </tr>
        </thead>
        <tbody>
          {dados.elementos_cq.map((e) => {
            const as = usos(e.id)
            return (
              <tr key={e.id}>
                <td className="font-medium">{e.nome}</td>
                <td>{e.nucleo ? <Selo tom="info">núcleo</Selo> : <span className="text-muted-foreground">não</span>}</td>
                <td className="tab text-right">{fracao(e.fracao_critica)}</td>
                <td className="truncate" title={as.map((a) => a.nome).join('\n')}>
                  {as.length ? `${plural(as.length, 'atividade', 'atividades')} · ${[...new Set(as.map((a) => a.tema))].join(', ')}` : <span className="text-muted-foreground">nenhuma</span>}
                </td>
                <td>{e.ativo ? 'ativo' : <Selo>inativo</Selo>}</td>
              </tr>
            )
          })}
        </tbody>
      </Tabela>
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
  const aba = rota.partes[0] === 'temas' || rota.partes[0] === 'elementos' ? rota.partes[0] : 'atividades'
  return (
    <>
      <CabecalhoModulo
        titulo="Catálogo"
        sub={`nacional, mantido pela CCAR${gerente ? '' : ' · só leitura'}`}
        ativa={aba}
        abas={[
          { id: 'atividades', rotulo: 'Atividades', href: href('catalogo/atividades') },
          { id: 'temas', rotulo: 'Temas', href: href('catalogo/temas') },
          { id: 'elementos', rotulo: 'Elementos de CQ', href: href('catalogo/elementos') },
        ]}
      />
      <Conteudo largura={1240}>
        {!dados && <Carregando erro={erro} />}
        {dados && aba === 'temas' && <Temas dados={dados} gerente={gerente} />}
        {dados && aba === 'elementos' && <Elementos dados={dados} />}
        {dados && aba === 'atividades' && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="max-w-[820px] text-nota text-muted-foreground">
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
