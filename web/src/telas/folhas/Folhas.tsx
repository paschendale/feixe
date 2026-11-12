import { useMemo, useState } from 'react'
import { Crosshair, Plus, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Lote, PassagemLote, StatusNacional } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { dataHora, num } from '@/lib/formato'
import { navegar, useRota } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { SITUACAO, STATUS, Status } from '@/lib/status'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { NovaFolha } from './NovaFolha'
import { NovoLoteLivre } from './NovoLoteLivre'

function Progresso({ feitas, total }: { feitas: number | null; total: number | null }) {
  if (!total) return <span className="text-muted-foreground">sem cargas</span>
  const pc = Math.round((100 * (feitas ?? 0)) / total)
  return (
    <span className="inline-flex items-center gap-2.5">
      <span className="tab w-20 text-right">
        {num(feitas ?? 0)}/{num(total)}
      </span>
      <span className="inline-block h-1 w-[80px] overflow-hidden rounded-sm bg-border">
        <span className="block h-full bg-aco" style={{ width: `${pc}%` }} />
      </span>
    </span>
  )
}

// Painel lateral da folha: trilho das passagens (D-72). As ações de andar com a folha chegam no B6.
function Lateral({ id, fechar }: { id: number; fechar: () => void }) {
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const { dados, erro } = useApi<Lote & { passagens: PassagemLote[] }>(`/api/lotes/${id}`, ['lote', 'carga'])
  return (
    <aside className="fixed top-[52px] right-0 bottom-0 z-40 flex w-[380px] flex-col gap-4 overflow-auto border-l bg-card p-6 shadow-[-8px_0_24px_rgba(0,0,0,.06)]">
      <div className="flex items-start justify-between">
        <div>
          <h2 className="tab text-lg font-semibold">{dados?.folha_revisao ?? '…'}</h2>
          {dados && (
            <p className="text-sm text-muted-foreground">
              {dados.projeto} · {dados.tema}
            </p>
          )}
        </div>
        <button onClick={fechar} aria-label="Fechar" className="opacity-60 hover:opacity-100">
          <X className="size-4" />
        </button>
      </div>
      {erro && <p className="text-sm text-destructive">{erro}</p>}
      {dados && (
        <>
          <div className="flex items-center justify-between text-sm">
            <Status s={dados.status_nacional} />
            <Button
              size="xs"
              variant="outline"
              disabled={!conectado}
              onClick={() => enviar(`/api/lotes/${id}/zoom`).catch((e) => avisar((e as Error).message, 'erro'))}
            >
              <Crosshair /> Zoom no QGIS
            </Button>
          </div>
          <ol className="flex flex-col">
            {dados.passagens.map((p) => {
              const agora = p.situacao === 'em_andamento' || (p.situacao === 'pendente' && !dados.passagens.some((x) => x.situacao === 'em_andamento'))
              return (
                <li key={p.id} className={cn('grid grid-cols-[22px_1fr_auto] items-center gap-2.5 border-b py-2.5 text-sm last:border-0', agora && 'font-semibold')}>
                  <span
                    className={cn(
                      'size-3 rounded-full border-2 border-[#C7D0DB]',
                      p.situacao === 'concluida' && 'border-aco bg-aco',
                      agora && 'border-ibge shadow-[0_0_0_3px_var(--aco-claro)]',
                    )}
                  />
                  <span>
                    {p.etapa}
                    {p.instancia > 1 ? ` (${p.instancia}ª)` : ''}
                    <span className="block text-xs font-normal text-muted-foreground">
                      {SITUACAO[p.situacao] ?? p.situacao}
                      {p.resultado ? ` · ${p.resultado}` : ''}
                      {p.concluida_em ? ` · ${dataHora(p.concluida_em)}` : ''}
                    </span>
                  </span>
                  <span className="tab text-xs font-normal text-muted-foreground">{p.cargas_total ? `${p.cargas_concluidas}/${p.cargas_total}` : ''}</span>
                </li>
              )
            })}
          </ol>
        </>
      )}
    </aside>
  )
}

export default function Folhas() {
  const { tem } = useSessao()
  const rota = useRota()
  const [status, setStatus] = useState<StatusNacional | ''>('')
  const [tema, setTema] = useState('')
  const [dialogo, setDialogo] = useState<'folha' | 'livre' | null>(null)
  const { dados, erro } = useApi<{ itens: Lote[] }>(`/api/lotes${status ? `?status=${status}` : ''}`, ['lote', 'carga'])
  const selecionado = rota.partes[0] ? Number(rota.partes[0]) : null
  const temas = useMemo(() => [...new Set((dados?.itens ?? []).map((l) => l.tema))].sort(), [dados])
  const itens = (dados?.itens ?? []).filter((l) => !tema || l.tema === tema)

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <Select className="w-56" value={tema} onChange={(e) => setTema(e.target.value)} aria-label="Tema">
          <option value="">Todos os temas</option>
          {temas.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </Select>
        <Select className="w-48" value={status} onChange={(e) => setStatus(e.target.value as StatusNacional | '')} aria-label="Status">
          <option value="">Todos os status</option>
          {Object.entries(STATUS).map(([k, v]) => (
            <option key={k} value={k}>
              {v.rotulo}
            </option>
          ))}
        </Select>
        <span className="text-sm text-muted-foreground">{dados ? `${num(itens.length)} ${itens.length === 1 ? 'lote' : 'lotes'}` : ''}</span>
        {tem('supervisor') && (
          <div className="ml-auto flex gap-2">
            <Button variant="outline" onClick={() => setDialogo('livre')}>
              <Plus /> Lote livre
            </Button>
            <Button onClick={() => setDialogo('folha')}>
              <Plus /> Novas folhas
            </Button>
          </div>
        )}
      </div>

      <div>
        <Card className="gap-0 overflow-hidden py-0">
          {erro && <p className="p-4 text-sm text-destructive">{erro}</p>}
          {!dados && !erro && <p className="p-4 text-sm text-muted-foreground">Carregando…</p>}
          {dados && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-4">Folha</TableHead>
                  <TableHead>Tema</TableHead>
                  <TableHead>Etapa</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Progresso</TableHead>
                  <TableHead>Responsável</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {itens.map((l) => (
                  <TableRow
                    key={l.id}
                    className={cn('cursor-pointer', selecionado === l.id && 'bg-accent')}
                    onClick={() => navegar(selecionado === l.id ? 'folhas' : `folhas/${l.id}`)}
                  >
                    <TableCell className="tab pl-4 font-semibold">{l.folha_revisao}</TableCell>
                    <TableCell className="whitespace-normal">{l.tema}</TableCell>
                    <TableCell className="whitespace-normal">
                      {l.etapa ?? '—'}
                      {l.situacao && <span className="text-muted-foreground"> · {SITUACAO[l.situacao] ?? l.situacao}</span>}
                    </TableCell>
                    <TableCell>
                      <Status s={l.status_nacional} />
                    </TableCell>
                    <TableCell>
                      <Progresso feitas={l.cargas_concluidas} total={l.cargas_total} />
                    </TableCell>
                    <TableCell className="max-w-44 truncate pr-4">{l.responsavel_nome ?? l.responsavel_principal ?? '—'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </Card>
        {selecionado && <Lateral key={selecionado} id={selecionado} fechar={() => navegar('folhas')} />}
      </div>

      <NovaFolha aberto={dialogo === 'folha'} fechar={() => setDialogo(null)} />
      <NovoLoteLivre aberto={dialogo === 'livre'} fechar={() => setDialogo(null)} />
    </>
  )
}
