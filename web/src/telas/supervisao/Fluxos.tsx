import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Bloco, Carregando, Conteudo, Nota, Selo } from '@/components/ds'
import type { Catalogo, EtapaFluxo, FluxoCompleto, Lote } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { plural } from '@/lib/formato'
import { href, navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { EditarFluxo } from '../fluxos/EditarFluxo'
import { pct } from './PlanosCQ'
import { NovoFluxo } from '../fluxos/NovoFluxo'

const ABERTAS = ['pendente', 'em_andamento']
const FASE: Record<string, string> = {
  aquisicao: 'aquisição',
  revisao: 'revisão',
  cq: 'CQ',
  correcao_inspecao: 'correção',
  correcao_topologica: 'topologia',
  envio_gcq: 'envio GCQ',
}

// O que acontece quando a etapa abre (D-109, D-136): cargas pela grade, amostras do CQ sorteadas com o padrão da etapa
// (sem padrão, os planos se criam na gaveta), cargas à mão ou nada a distribuir (a etapa começa já em andamento).
function aoAbrir(e: EtapaFluxo) {
  const geram = e.atividades.filter((a) => a.geracao !== 'nenhuma')
  if (e.fase === 'cq') {
    if (!e.atividades.length) return { texto: 'sem atividade de CQ: escolha no editor as medidas a inspecionar', alerta: true }
    if (e.nivel_inspecao && e.lqa != null) return { texto: `sorteia as amostras de cada atividade e gera as cargas (nível ${e.nivel_inspecao}, LQA ${pct(e.lqa)})`, alerta: false }
    return { texto: 'sem nível e LQA padrão: os planos de CQ se criam na gaveta de cada folha', alerta: true }
  }
  if (geram.some((a) => a.geracao === 'grade')) return null
  // Correção de inspeção (D5): a carga é a folha inteira, e quem a recebe trata as ocorrências de todas as revisões.
  if (e.fase === 'correcao_inspecao')
    return geram.length
      ? { texto: 'a folha inteira vai a quem você distribuir, que trata as ocorrências de todas as revisões', alerta: false }
      : { texto: 'sem atividade de correção: ninguém recebe a folha para tratar as ocorrências; escolha a atividade no editor', alerta: true }
  if (geram.length) return { texto: 'cargas não saem da grade: inicie pela gaveta', alerta: true }
  return { texto: 'sem cargas: começa assim que abre, sem nada a distribuir', alerta: true }
}

// Supervisão › Fluxos: cada fluxo é a sequência de etapas de um tema na unidade; as folhas andam por ele quando o
// supervisor decide. À direita, quantas folhas estão em cada etapa agora.
export default function Fluxos() {
  const { tem } = useSessao()
  const avisar = useAvisar()
  const rota = useRota()
  const supervisor = tem('supervisor')
  const { dados, erro } = useApi<{ itens: FluxoCompleto[] }>('/api/fluxos/completos', ['fluxo'])
  const { dados: lotes } = useApi<{ itens: Lote[] }>('/api/lotes', ['lote'])
  const { dados: catalogo } = useApi<Catalogo>('/api/catalogo', ['atividade'])
  const [editar, setEditar] = useState<FluxoCompleto | null>(null)
  const [novo, setNovo] = useState(false)

  if (!dados)
    return (
      <Conteudo>
        <Carregando erro={erro} />
      </Conteudo>
    )
  const escolhido = Number(rota.partes[1]) || dados.itens.find((f) => f.ativo)?.id || dados.itens[0]?.id
  const f = dados.itens.find((x) => x.id === escolhido)
  const doFluxo = (lotes?.itens ?? []).filter((l) => l.id_fluxo === f?.id)
  const ultimaOrdem = Math.max(0, ...(f?.etapas ?? []).map((e) => e.ordem ?? 0))
  const noFim = doFluxo.filter((l) => !ABERTAS.includes(l.situacao ?? '') && f?.etapas.find((e) => e.nome === l.etapa)?.ordem === ultimaOrdem).length

  async function alternar(x: FluxoCompleto) {
    try {
      await enviar(`/api/fluxos/${x.id}`, { ativo: !x.ativo }, 'PUT')
      avisar(`${x.nome}: ${x.ativo ? 'desativado' : 'ativado'}`)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  return (
    <Conteudo className="flex-row flex-wrap items-start gap-6">
      <div className="flex min-w-[260px] flex-[1_1_280px] flex-col gap-3">
        <p className="text-nota text-muted-foreground">Cada fluxo é a sequência de etapas de um tema na sua unidade. As folhas andam por ele quando você decide.</p>
        <nav aria-label="Fluxos" className="flex flex-col overflow-hidden rounded-xl bg-card shadow-cartao">
          {dados.itens.length === 0 && <span className="p-4 text-muted-foreground">Nenhum fluxo na unidade.</span>}
          {dados.itens.map((x) => (
            <a
              key={x.id}
              href={href(`supervisao/fluxos/${x.id}`)}
              aria-current={x.id === f?.id ? 'true' : undefined}
              className={cn('flex flex-col gap-0.5 border-b border-linha px-4 py-3 last:border-0', x.id === f?.id ? 'bg-primary-suave' : 'hover:bg-preenchimento-2', !x.ativo && 'opacity-60')}
            >
              <b className={cn(x.id === f?.id && 'text-primary')}>{x.nome}</b>
              <span className="text-nota text-muted-foreground">
                {plural(x.etapas.length, 'etapa', 'etapas')} · {plural(x.lotes, 'folha', 'folhas')}
                {!x.ativo ? ' · inativo' : ''}
              </span>
            </a>
          ))}
        </nav>
        {supervisor && catalogo && (
          <>
            <Button variant="outline" className="self-start" onClick={() => setNovo(true)}>
              <Plus /> Novo fluxo
            </Button>
            <span className="text-rodape text-muted-foreground">Novo fluxo parte do modelo da CCAR (aquisição, revisão, CQ, correção de inspeção, correção topológica, envio à GCQ) ou de uma cópia do fluxo de outra unidade.</span>
          </>
        )}
      </div>

      {f && (
        <Bloco className="min-w-[340px] flex-[3_1_640px] gap-4 p-6">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-titulo-2 font-semibold">{f.nome}</h2>
            <span className="text-muted-foreground">
              {f.projeto} · {f.tema} · {f.ativo ? 'ativo' : 'inativo'}
            </span>
          </div>
          {f.etapas.filter((e) => aoAbrir(e)?.alerta && ['aquisicao', 'revisao', 'correcao_topologica'].includes(e.fase)).length > 0 && (
            <Nota tom="alerta">
              {(() => {
                const sem = f.etapas.filter((e) => aoAbrir(e)?.alerta && ['aquisicao', 'revisao', 'correcao_topologica'].includes(e.fase))
                return (
                  <>
                    {sem.map((e) => e.nome).join(', ')} {sem.length === 1 ? 'não gera' : 'não geram'} cargas pela grade: ao abrir, não há o que distribuir. Se a etapa tem trabalho a dividir entre a equipe, escolha no editor uma atividade com cargas pela grade.
                  </>
                )
              })()}
            </Nota>
          )}
          {noFim > 0 && (
            <Nota tom="alerta">
              {plural(noFim, 'folha terminou', 'folhas terminaram')} a última etapa e não {noFim === 1 ? 'tem' : 'têm'} próxima. Para a CCAR, {noFim === 1 ? 'segue' : 'seguem'} no status dessa etapa até se decidir como encerrar a folha.
            </Nota>
          )}
          <ol className="flex flex-col">
            {f.etapas.map((e) => {
              const aqui = doFluxo.filter((l) => l.etapa === e.nome)
              const agora = aqui.filter((l) => ABERTAS.includes(l.situacao ?? '')).length
              const paradas = aqui.length - agora
              return (
                <li key={e.id} className="grid grid-cols-[32px_1fr_auto] items-center gap-x-3 gap-y-1 border-b border-linha py-3 last:border-0 md:grid-cols-[32px_1fr_110px_220px_120px]">
                  <span className="grid size-7 place-items-center rounded-full bg-primary-suave text-rodape font-semibold text-primary">{e.ordem}</span>
                  <div className="flex min-w-0 flex-col">
                    <b>{e.nome}</b>
                    <span className="truncate text-nota text-muted-foreground" title={e.atividades.map((a) => a.nome).join('\n')}>
                      {e.atividades.map((a) => a.nome).join(', ') || 'sem atividade'}
                    </span>
                    {aoAbrir(e) && (
                      <span className={cn('text-rodape', aoAbrir(e)!.alerta ? 'text-alerta' : 'text-muted-foreground')}>
                        {aoAbrir(e)!.texto}
                      </span>
                    )}
                  </div>
                  <Selo className="hidden justify-self-start font-medium md:inline-flex">{FASE[e.fase] ?? e.fase_nome ?? e.fase}</Selo>
                  <span className="hidden text-nota text-muted-foreground md:inline">
                    {[e.obrigatoria ? 'obrigatória' : 'opcional', e.repetivel && 'repetível', e.conta_revisao && 'conta revisão', e.fracao_critica != null && `fração crítica ${pct(e.fracao_critica)}`].filter(Boolean).join(' · ')}
                  </span>
                  <span className="text-right text-nota">
                    {agora > 0 && <b className="text-primary">{plural(agora, 'folha agora', 'folhas agora')}</b>}
                    {agora > 0 && paradas > 0 && <br />}
                    {paradas > 0 && (
                      <span className="text-alerta">
                        {paradas} {e.ordem === ultimaOrdem ? 'no fim' : paradas === 1 ? 'parada' : 'paradas'}
                      </span>
                    )}
                    {!agora && !paradas && <span className="text-muted-foreground">0</span>}
                  </span>
                </li>
              )
            })}
          </ol>
          {supervisor && (
            <div className="flex flex-wrap gap-2">
              {f.ativo && (
                <Button onClick={() => navegar(`supervisao/folhas?novas=${f.id}`)}>
                  {doFluxo.length ? 'Pôr mais folhas neste fluxo' : 'Próximo: pôr as folhas deste fluxo'}
                </Button>
              )}
              <Button variant="outline" onClick={() => setEditar(f)} disabled={!catalogo}>
                Editar etapas
              </Button>
              <Button variant="outline" onClick={() => alternar(f)}>
                {f.ativo ? 'Desativar' : 'Ativar'}
              </Button>
            </div>
          )}
          <span className="text-rodape text-muted-foreground">
            No editor: subir, descer e tirar etapa, escolher a atividade de cada uma (as de CQ, uma por medida) e marcar obrigatória, repetível e conta revisão; no CQ, o nível de inspeção, o LQA e a fração crítica padrão. A etapa com atividade pela grade ganha as cargas quando abre; a de CQ com padrão já abre com as amostras sorteadas; a etapa sem atividade não tem cargas e começa assim que abre.
          </span>
        </Bloco>
      )}
      {catalogo && <EditarFluxo fluxo={editar} catalogo={catalogo} fechar={() => setEditar(null)} />}
      {catalogo && (
        <NovoFluxo
          catalogo={catalogo}
          aberto={novo}
          fechar={(x) => {
            setNovo(false)
            if (x) setEditar(x)
          }}
        />
      )}
    </Conteudo>
  )
}
