import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Bloco, COR, Carregando, Conteudo } from '@/components/painel'
import type { Catalogo, FluxoCompleto, Lote } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { plural } from '@/lib/formato'
import { href, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { EditarFluxo } from '../fluxos/EditarFluxo'
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
        <p className="text-[13px] text-muted-foreground">Cada fluxo é a sequência de etapas de um tema na sua unidade. As folhas andam por ele quando você decide.</p>
        <nav aria-label="Fluxos" className="flex flex-col overflow-hidden rounded-[10px] border bg-card">
          {dados.itens.length === 0 && <span className="p-4 text-sm text-muted-foreground">Nenhum fluxo na unidade.</span>}
          {dados.itens.map((x) => (
            <a
              key={x.id}
              href={href(`supervisao/fluxos/${x.id}`)}
              aria-current={x.id === f?.id ? 'true' : undefined}
              className={cn('flex flex-col gap-0.5 border-b border-[#EEF1F4] px-4 py-3 last:border-0', x.id === f?.id ? 'bg-[#EEF3FA] shadow-[inset_3px_0_0_var(--ibge)]' : 'hover:bg-[#F7F9FB]', !x.ativo && 'opacity-60')}
            >
              <b>{x.nome}</b>
              <span className="text-[13px] text-muted-foreground">
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
            <span className="text-xs text-muted-foreground">Novo fluxo parte do modelo da CCAR (aquisição, revisão, CQ, correção de inspeção, correção topológica, envio à GCQ) ou de uma cópia do fluxo de outra unidade.</span>
          </>
        )}
      </div>

      {f && (
        <Bloco className="min-w-[340px] flex-[3_1_640px] gap-4 p-6">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h2 className="text-xl font-semibold">{f.nome}</h2>
            <span className="text-muted-foreground">
              {f.projeto} · {f.tema} · {f.ativo ? 'ativo' : 'inativo'}
            </span>
          </div>
          {noFim > 0 && (
            <div className="rounded-lg px-3.5 py-2.5 text-[13px]" style={{ background: COR.alertaFundo, color: '#5C3D00' }}>
              {plural(noFim, 'folha terminou', 'folhas terminaram')} a última etapa e não {noFim === 1 ? 'tem' : 'têm'} próxima. Para a CCAR, {noFim === 1 ? 'segue' : 'seguem'} no status dessa etapa até se decidir como encerrar a folha.
            </div>
          )}
          <ol className="flex flex-col">
            {f.etapas.map((e) => {
              const aqui = doFluxo.filter((l) => l.etapa === e.nome)
              const agora = aqui.filter((l) => ABERTAS.includes(l.situacao ?? '')).length
              const paradas = aqui.length - agora
              return (
                <li key={e.id} className="grid grid-cols-[32px_1fr_auto] items-center gap-x-3 gap-y-1 border-b border-[#EEF1F4] py-3 last:border-0 md:grid-cols-[32px_1fr_110px_220px_120px]">
                  <span className="grid size-7 place-items-center rounded-full bg-aco-claro text-xs font-semibold text-ibge">{e.ordem}</span>
                  <div className="flex min-w-0 flex-col">
                    <b>{e.nome}</b>
                    <span className="truncate text-[13px] text-muted-foreground" title={e.atividades.map((a) => a.nome).join('\n')}>
                      {e.atividades.map((a) => a.nome).join(', ') || 'sem atividade'}
                    </span>
                  </div>
                  <span className="hidden justify-self-start rounded-full bg-[#E9EDF2] px-2 py-0.5 text-xs md:inline">{FASE[e.fase] ?? e.fase_nome ?? e.fase}</span>
                  <span className="hidden text-[13px] text-muted-foreground md:inline">
                    {[e.obrigatoria ? 'obrigatória' : 'opcional', e.repetivel && 'repetível', e.conta_revisao && 'conta revisão', e.fracao_critica != null && `fração crítica ${e.fracao_critica}%`].filter(Boolean).join(' · ')}
                  </span>
                  <span className="text-right text-[13px]">
                    {agora > 0 && <b className="text-ibge">{plural(agora, 'folha agora', 'folhas agora')}</b>}
                    {agora > 0 && paradas > 0 && <br />}
                    {paradas > 0 && (
                      <span style={{ color: COR.alerta }}>
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
              <Button onClick={() => setEditar(f)} disabled={!catalogo}>
                Editar etapas
              </Button>
              <Button variant="outline" onClick={() => alternar(f)}>
                {f.ativo ? 'Desativar' : 'Ativar'}
              </Button>
            </div>
          )}
          <span className="text-xs text-muted-foreground">No editor: subir, descer e tirar etapa, escolher a atividade de cada uma (as de CQ, uma por medida) e marcar obrigatória, repetível e conta revisão.</span>
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
