import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import type { EstadoLote, FluxoCompleto, Historico, Lote, PassagemLote } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { dataHora } from '@/lib/formato'
import { enviar, useApi } from '@/lib/useApi'

type Pedido = { titulo: string; caminho: string; corpo?: Record<string, unknown>; abrir?: boolean }

const ACAO: Record<string, string> = {
  abrir: 'abriu',
  repetir: 'abriu de novo',
  iniciar: 'iniciou',
  concluir: 'concluiu',
  pular: 'pulou',
  reabrir: 'reabriu',
  gcq_aprovada: 'registrou: aprovada pela GCQ',
  gcq_devolvida: 'registrou: devolvida pela GCQ',
}

// Andar com a folha (B6): toda ação é do supervisor, com observação, e vai para o histórico. O plugin só sugere a
// próxima etapa; nada avança sozinho.
export function AndarFolha({ lote, passagens }: { lote: Lote; passagens: PassagemLote[] }) {
  const avisar = useAvisar()
  const { dados: fluxos } = useApi<{ itens: FluxoCompleto[] }>('/api/fluxos/completos', ['fluxo'])
  const { dados: estado } = useApi<EstadoLote>(`/api/lotes/${lote.id}/estado`, ['lote'])
  const { dados: hist } = useApi<{ itens: Historico[] }>(`/api/lotes/${lote.id}/historico`, ['lote'])
  const [pedido, setPedido] = useState<Pedido | null>(null)
  const [obs, setObs] = useState('')
  const [etapa, setEtapa] = useState<number | null>(null)
  const [expor, setExpor] = useState(false)
  const [ocupado, setOcupado] = useState(false)

  const fluxo = fluxos?.itens.find((f) => f.id === lote.id_fluxo)
  const etapaDe = (p: PassagemLote) => fluxo?.etapas.find((e) => e.id === p.id_fluxo_etapa)
  const aberta = passagens.find((p) => p.situacao === 'pendente' || p.situacao === 'em_andamento')
  const naoPuladas = passagens.filter((p) => p.situacao !== 'pulada')
  const ultima = naoPuladas.length ? naoPuladas.reduce((a, b) => (a.id > b.id ? a : b)) : null

  function pedir(p: Pedido) {
    setPedido(p)
    setObs('')
    if (p.abrir) {
      setEtapa(estado?.sugestao?.id ?? fluxo?.etapas[0]?.id ?? null)
      setExpor(false)
    }
  }

  async function confirmar() {
    if (!pedido) return
    setOcupado(true)
    try {
      const corpo = { ...pedido.corpo, observacao: obs, ...(pedido.abrir ? { id_fluxo_etapa: etapa, expor_ocorrencias: expor } : {}) }
      const r = await enviar<EstadoLote>(pedido.caminho, corpo)
      avisar(`${lote.folha_revisao}: ${pedido.titulo.toLowerCase()} · ${r.etapa ?? ''}`)
      setPedido(null)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  const botoes: Pedido[] = []
  if (aberta?.situacao === 'pendente') {
    botoes.push({ titulo: 'Iniciar etapa', caminho: `/api/lote_etapas/${aberta.id}/iniciar` })
    if (etapaDe(aberta) && !etapaDe(aberta)!.obrigatoria) botoes.push({ titulo: 'Pular etapa', caminho: `/api/lote_etapas/${aberta.id}/pular` })
  }
  if (aberta?.situacao === 'em_andamento') {
    if (aberta.fase === 'envio_gcq') {
      botoes.push({ titulo: 'Aprovada pela GCQ', caminho: `/api/lote_etapas/${aberta.id}/gcq`, corpo: { resultado: 'aprovada' } })
      botoes.push({ titulo: 'Devolvida pela GCQ', caminho: `/api/lote_etapas/${aberta.id}/gcq`, corpo: { resultado: 'devolvida' } })
    } else botoes.push({ titulo: 'Concluir etapa', caminho: `/api/lote_etapas/${aberta.id}/concluir` })
  }
  if (!aberta) {
    botoes.push({ titulo: 'Abrir etapa', caminho: `/api/lotes/${lote.id}/passagens`, abrir: true })
    if (ultima?.situacao === 'concluida') botoes.push({ titulo: 'Reabrir a última', caminho: `/api/lote_etapas/${ultima.id}/reabrir` })
  }

  return (
    <div className="flex flex-col gap-3 border-t pt-4">
      {estado?.sugestao && !aberta && (
        <p className="text-sm">
          Sugestão do Feixe: <b>{estado.sugestao.nome}</b>
        </p>
      )}
      {!pedido && (
        <div className="flex flex-wrap gap-2">
          {botoes.map((b, i) => (
            <Button key={b.titulo} size="sm" variant={i === 0 ? 'default' : 'outline'} onClick={() => pedir(b)}>
              {b.titulo}
            </Button>
          ))}
        </div>
      )}
      {pedido && (
        <div className="flex flex-col gap-3 rounded-lg border bg-accent/40 p-3">
          <p className="text-sm font-semibold">{pedido.titulo}</p>
          {pedido.abrir && (
            <>
              <div className="grid gap-1.5">
                <Label htmlFor="etapa-abrir">Etapa</Label>
                <Select id="etapa-abrir" value={etapa ?? ''} onChange={(e) => setEtapa(Number(e.target.value))}>
                  {fluxo?.etapas.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.ordem}. {e.nome}
                      {e.id === estado?.sugestao?.id ? ' (sugerida)' : ''}
                    </option>
                  ))}
                </Select>
              </div>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={expor} onChange={(e) => setExpor(e.target.checked)} />
                <span>
                  Incluir as correções a fazer
                  <span className="block text-xs text-muted-foreground">Mostra a quem executar as ocorrências das passagens anteriores. Sem isso, a revisão é às cegas.</span>
                </span>
              </label>
            </>
          )}
          <div className="grid gap-1.5">
            <Label htmlFor="obs-acao">Observação</Label>
            <Textarea id="obs-acao" value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Fica no histórico da folha" />
          </div>
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setPedido(null)}>
              Cancelar
            </Button>
            <Button size="sm" onClick={confirmar} disabled={ocupado || !obs.trim() || (pedido.abrir && !etapa)}>
              Confirmar
            </Button>
          </div>
        </div>
      )}
      {hist && hist.itens.length > 0 && (
        <div className="flex flex-col gap-2 border-t pt-3">
          <p className="text-xs font-semibold text-muted-foreground uppercase">Histórico</p>
          <ul className="flex flex-col gap-2 text-sm">
            {hist.itens.slice(0, 12).map((h, i) => (
              <li key={i}>
                <span className="text-muted-foreground">{dataHora(h.em)} · </span>
                {h.por_nome.split(' ')[0]} {ACAO[h.acao] ?? h.acao} {h.etapa}
                {h.instancia > 1 ? ` (${h.instancia}ª)` : ''}
                {h.observacao && <span className="block text-xs text-muted-foreground">“{h.observacao}”</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
