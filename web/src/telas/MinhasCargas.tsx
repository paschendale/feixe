import { useState } from 'react'
import { Check, Crosshair, Play, Undo2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Carga, Passagem, Progresso, ResumoCargas } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { dataHora, mesAno, num, plural } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

const JANELA_DESFAZER_MS = 24 * 3600 * 1000
const ABERTAS = ['pendente', 'em_andamento']

function Barra({ feitas, total }: { feitas: number; total: number }) {
  const pc = total ? Math.round((100 * feitas) / total) : 0
  return (
    <span className="inline-flex items-center gap-2.5">
      <span className="tab w-16 text-right">
        {num(feitas)}/{num(total)}
      </span>
      <span className="inline-block h-1 w-[90px] overflow-hidden rounded-sm bg-border">
        <span className="block h-full bg-aco" style={{ width: `${pc}%` }} />
      </span>
    </span>
  )
}

// Hook das ações sobre uma carga: chama a API e avisa o resultado (as telas recarregam pelo evento SSE "carga").
function useAcoes() {
  const avisar = useAvisar()
  const [ocupado, setOcupado] = useState<number | 'proxima' | null>(null)
  async function rodar<T>(chave: number | 'proxima', fn: () => Promise<T>, ok?: (r: T) => string | null) {
    setOcupado(chave)
    try {
      const r = await fn()
      const msg = ok?.(r)
      if (msg) avisar(msg)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(null)
    }
  }
  const prog = (p: Progresso) => `${p.folha_revisao} · ${p.concluidas}/${p.total}`
  return {
    ocupado,
    concluir: (c: Carga) =>
      rodar(c.id, () => enviar<{ progresso: Progresso }>(`/api/cargas/${c.id}/concluir`), (r) => `Carga concluída · ${prog(r.progresso)}`),
    desfazer: (c: Carga) =>
      rodar(c.id, () => enviar<{ progresso: Progresso }>(`/api/cargas/${c.id}/desfazer`), (r) => `Conclusão desfeita · ${prog(r.progresso)}`),
    zoom: (c: Carga) => rodar(c.id, () => enviar(`/api/cargas/${c.id}/zoom`)),
    proxima: () =>
      rodar(
        'proxima',
        () => enviar<{ carga: Carga | null }>('/api/cargas/proxima', {}),
        (r) => (r.carga ? `Próxima carga no QGIS: ${r.carga.folha_revisao}` : 'Você não tem carga pendente.'),
      ),
  }
}

function CargasDaPassagem({ p, acoes }: { p: Passagem; acoes: ReturnType<typeof useAcoes> }) {
  const { conectado } = useSessao()
  const { dados, erro } = useApi<{ itens: Carga[] }>(`/api/cargas?lote_etapa=${p.id_lote_etapa}`, ['carga'])
  const aberta = ABERTAS.includes(p.situacao)
  if (erro) return <p className="px-4 py-3 text-sm text-destructive">{erro}</p>
  if (!dados) return <p className="px-4 py-3 text-sm text-muted-foreground">Carregando…</p>
  return (
    <Table>
      <TableBody>
        {dados.itens.map((c) => {
          const recente = c.concluido_em && Date.now() - new Date(c.concluido_em).getTime() < JANELA_DESFAZER_MS
          return (
            <TableRow key={c.id}>
              <TableCell className="pl-8 font-mono text-xs text-muted-foreground">{c.geocodigo ?? `#${c.id}`}</TableCell>
              <TableCell>{c.atividade}</TableCell>
              <TableCell>
                {c.concluido ? (
                  <span className="text-muted-foreground">Concluída {dataHora(c.concluido_em)}</span>
                ) : (
                  <span className="font-medium">Pendente</span>
                )}
              </TableCell>
              <TableCell className="text-right">
                <div className="flex justify-end gap-1.5">
                  <Button size="xs" variant="ghost" onClick={() => acoes.zoom(c)} disabled={!conectado || acoes.ocupado === c.id}>
                    <Crosshair /> Zoom
                  </Button>
                  {aberta && !c.concluido && (
                    <Button size="xs" variant="outline" onClick={() => acoes.concluir(c)} disabled={acoes.ocupado === c.id}>
                      <Check /> Concluir
                    </Button>
                  )}
                  {aberta && c.concluido && recente && (
                    <Button size="xs" variant="ghost" onClick={() => acoes.desfazer(c)} disabled={acoes.ocupado === c.id}>
                      <Undo2 /> Desfazer
                    </Button>
                  )}
                </div>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

export default function MinhasCargas() {
  const { conectado } = useSessao()
  const { dados, erro } = useApi<ResumoCargas>('/api/cargas/resumo', ['carga'])
  const [aberta, setAberta] = useState<number | null>(null)
  const acoes = useAcoes()

  if (erro) return <p className="text-sm text-destructive">{erro}</p>
  if (!dados) return <p className="text-sm text-muted-foreground">Carregando…</p>

  return (
    <>
      <div className="flex items-start justify-between gap-6">
        <p className="text-xl leading-relaxed">
          {dados.concluidas > 0 ? (
            <>
              Você concluiu <b className="tab">{num(dados.concluidas)}</b> cargas
              {dados.desde ? ` desde ${mesAno(dados.desde)}` : ''}.{' '}
            </>
          ) : null}
          {dados.pendentes > 0 ? (
            <>
              Faltam <b className="tab">{num(dados.pendentes)}</b> em {plural(dados.folhas_pendentes, 'folha', 'folhas')}.
            </>
          ) : (
            'Nenhuma carga pendente.'
          )}
        </p>
        <Button onClick={acoes.proxima} disabled={!conectado || dados.pendentes === 0 || acoes.ocupado === 'proxima'}>
          <Play /> Próxima carga
        </Button>
      </div>

      <Card className="gap-0 py-0">
        {dados.passagens.length === 0 ? (
          <p className="p-4 text-sm text-muted-foreground">Nenhuma carga atribuída a você em folhas abertas.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">Folha</TableHead>
                <TableHead>Tema</TableHead>
                <TableHead>Etapa</TableHead>
                <TableHead>Progresso</TableHead>
                <TableHead>Última conclusão</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {dados.passagens.map((p) => (
                <PassagemLinhas key={p.id_lote_etapa} p={p} aberta={aberta === p.id_lote_etapa} alternar={() => setAberta(aberta === p.id_lote_etapa ? null : p.id_lote_etapa)} acoes={acoes} />
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </>
  )
}

function PassagemLinhas({ p, aberta, alternar, acoes }: { p: Passagem; aberta: boolean; alternar: () => void; acoes: ReturnType<typeof useAcoes> }) {
  const encerrada = !ABERTAS.includes(p.situacao)
  return (
    <>
      <TableRow className={cn('cursor-pointer', aberta && 'bg-accent')} onClick={alternar} aria-expanded={aberta}>
        <TableCell className="tab pl-4 font-semibold">{p.folha_revisao}</TableCell>
        <TableCell>{p.tema}</TableCell>
        <TableCell>
          {p.etapa}
          {encerrada && <span className="text-muted-foreground"> · encerrada</span>}
        </TableCell>
        <TableCell>
          <Barra feitas={p.concluidas} total={p.total} />
        </TableCell>
        <TableCell className="text-muted-foreground">{dataHora(p.ultima_conclusao)}</TableCell>
      </TableRow>
      {aberta && (
        <TableRow className="hover:bg-transparent">
          <TableCell colSpan={5} className="p-0">
            <CargasDaPassagem p={p} acoes={acoes} />
          </TableCell>
        </TableRow>
      )}
    </>
  )
}
