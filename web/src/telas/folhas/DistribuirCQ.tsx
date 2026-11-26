import { useEffect, useMemo, useRef, useState } from 'react'
import { Colunas, RotuloEstavel } from '@/components/painel'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import type { ResultadoDistribuicaoCQ, SugestaoDistribuicaoCQ } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { lista, num, plural } from '@/lib/formato'
import { enviar } from '@/lib/useApi'
import { cn } from '@/lib/utils'

const primeiro = (n: string | null | undefined) => (n ?? '').split(' ').slice(0, 2).join(' ')
const folhasTxt = (fs: string[]) => (fs.length <= 6 ? lista(fs) : `${lista(fs.slice(0, 5))} e mais ${num(fs.length - 5)}`)

// Distribuir as amostras de CQ (D-147). No CQ várias pessoas avaliam a mesma folha: as amostras das folhas escolhidas
// se juntam e se repartem entre os avaliadores marcados, na proporção do peso de cada um (em % ou em amostras, a mesma
// coisa vista de dois jeitos). Cada avaliador recebe uma fatia de todos os elementos, em blocos contínuos na ordem da
// folha e da grade. Sem fila: quem é marcado recebe agora, e a etapa de CQ começa. Redistribuir é o mesmo diálogo: só
// as não avaliadas mudam de mão. Quem executou a folha não avalia (regra fixa); a equipe vem lembrada da última vez.
export function DistribuirCQ({ lotes, fechar }: { lotes: number[]; fechar: (feito: boolean) => void }) {
  const avisar = useAvisar()
  const [dados, setDados] = useState<SugestaoDistribuicaoCQ | null>(null)
  const [pesos, setPesos] = useState<Record<string, number>>({})
  const [previa, setPrevia] = useState<ResultadoDistribuicaoCQ | null>(null)
  const [erroPrevia, setErroPrevia] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const pedido = useRef(0)

  useEffect(() => {
    if (!lotes.length) return
    setDados(null)
    setPrevia(null)
    enviar<SugestaoDistribuicaoCQ>('/api/distribuir_cq/sugestao', { lotes })
      .then((d) => {
        setDados(d)
        setPesos(Object.fromEntries(d.pessoas.filter((p) => !p.motivo && p.peso > 0).map((p) => [p.conta, p.peso])))
      })
      .catch((e) => avisar((e as Error).message, 'erro'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotes])

  const marcados = useMemo(() => Object.fromEntries(Object.entries(pesos).filter(([, p]) => p > 0)), [pesos])
  const soma = Object.values(marcados).reduce((a, b) => a + b, 0)

  // A prévia vem do servidor (a mesma conta que grava), um instante depois da última mudança.
  useEffect(() => {
    if (!dados || !dados.total) return
    if (!Object.keys(marcados).length) {
      setPrevia(null)
      return
    }
    const n = ++pedido.current
    const t = window.setTimeout(() => {
      enviar<ResultadoDistribuicaoCQ>('/api/distribuir_cq', { lotes, pesos: marcados, previa: true })
        .then((r) => {
          if (n !== pedido.current) return
          setPrevia(r)
          setErroPrevia(null)
        })
        .catch((e) => n === pedido.current && setErroPrevia((e as Error).message))
    }, 250)
    return () => window.clearTimeout(t)
  }, [dados, marcados, lotes])

  const aptos = (dados?.pessoas ?? []).filter((p) => !p.motivo || p.com > 0)
  const foraDaEquipe = (dados?.pessoas ?? []).filter((p) => p.motivo && !p.com)
  const doServidor = useMemo(() => new Map((previa?.pessoas ?? []).map((p) => [p.conta, p])), [previa])
  const elementos = dados?.elementos ?? []
  const total = dados?.total ?? 0

  function marcar(conta: string, sim: boolean) {
    setPesos((x) => {
      if (!sim) return { ...x, [conta]: 0 }
      const outros = Object.values(x).filter((p) => p > 0).length
      return { ...x, [conta]: Math.max(1, Math.round(total / (outros + 1))) }
    })
  }
  const pct = (p: number) => (total ? Math.round((1000 * p) / total) / 10 : 0)

  async function distribuir() {
    setOcupado(true)
    try {
      const r = await enviar<ResultadoDistribuicaoCQ>('/api/distribuir_cq', { lotes, pesos: marcados, previa: false })
      const quem = r.pessoas.filter((p) => p.total > p.avaliadas).map((p) => `${primeiro(p.nome)} (${num(p.total - p.avaliadas)})`)
      avisar(`Amostras distribuídas: ${plural(r.movidas, 'mudou de mão', 'mudaram de mão')}. Com cada um agora, a avaliar: ${lista(quem)}. A etapa de CQ começou.`)
      fechar(true)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  const nFolhas = dados?.folhas.length ?? lotes.length
  const avaliadas = (dados?.folhas ?? []).reduce((n, f) => n + f.avaliadas, 0)
  return (
    <Dialog open={lotes.length > 0} onOpenChange={(v) => !v && fechar(false)}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Distribuir as amostras de {nFolhas === 1 && dados?.folhas[0] ? dados.folhas[0].folha_revisao : plural(nFolhas, 'folha', 'folhas')}</DialogTitle>
          <DialogDescription>
            As amostras {nFolhas > 1 ? 'das folhas se juntam e ' : ''}se repartem entre os avaliadores marcados, na proporção que você escolher. Cada um recebe uma fatia de todos os elementos, em blocos contínuos da folha. Quem é marcado recebe agora, sem fila, e a etapa de CQ começa. Quem executou a folha não avalia.
          </DialogDescription>
        </DialogHeader>
        {!dados && <div className="grid h-[240px] place-items-center rounded-md border text-sm text-muted-foreground">Montando a sugestão…</div>}
        {dados && !total && (
          <p className="text-sm text-muted-foreground">Nenhuma destas folhas tem amostras de CQ: os planos ainda não foram criados (gaveta da folha).</p>
        )}
        {dados && total > 0 && (
          <>
            <div className="flex flex-col gap-1 rounded-lg bg-[#EEF3FA] px-3.5 py-2.5 text-[13px] text-[#1C2F4A]">
              <span>
                <b>{plural(total, 'amostra', 'amostras')}</b> em {folhasTxt(dados.folhas.map((f) => f.folha_revisao))}
                {avaliadas > 0 && `, ${num(avaliadas)} já avaliadas (ficam com quem avaliou)`} ·{' '}
                {elementos.map((e) => `${e.elemento} ${num(e.amostras)}`).join(' · ')}
              </span>
              <span className="text-xs text-texto-2">
                {dados.origem === 'atual' && 'Abre com a divisão que estas folhas já têm. Mudar os pesos redistribui só as amostras ainda não avaliadas.'}
                {dados.origem === 'ultima' && `Abre com a mesma equipe e a mesma proporção da última distribuição desta etapa (${dados.origem_folha}).`}
                {dados.origem === 'igual' && 'Primeira distribuição desta etapa: partes iguais entre os avaliadores aptos. Da próxima vez, o Feixe lembra a equipe.'}
                {dados.sem_perfil_v && ' Ninguém tem perfil de avaliador (V) no projeto: aparece toda a equipe; desmarque quem não avalia.'}
              </span>
            </div>
            <div className="max-h-[46vh] overflow-auto rounded-md border">
              <table className="w-full table-fixed border-collapse text-sm">
                <Colunas larguras={['34%', '13%', '15%', undefined]} />
                <thead className="sticky top-0 bg-card">
                  <tr className="text-left text-xs text-muted-foreground">
                    <th className="border-b py-2 pr-2 pl-3 font-medium">Avaliador</th>
                    <th className="border-b px-2 py-2 font-medium">%</th>
                    <th className="border-b px-2 py-2 font-medium">Amostras</th>
                    <th className="border-b py-2 pr-3 pl-2 font-medium">Fica com</th>
                  </tr>
                </thead>
                <tbody>
                  {aptos.map((p) => {
                    const peso = pesos[p.conta] ?? 0
                    const ligado = peso > 0
                    const r = doServidor.get(p.conta)
                    const podeMarcar = !p.motivo
                    return (
                      <tr key={p.conta} className={cn('border-b border-linha last:border-0', !ligado && 'text-muted-foreground')}>
                        <td className="py-2 pr-2 pl-3">
                          <label className="flex items-start gap-2">
                            <input type="checkbox" className="mt-0.5" checked={ligado} disabled={!podeMarcar} onChange={(e) => marcar(p.conta, e.target.checked)} aria-label={`Incluir ${p.nome}`} />
                            <span className="min-w-0">
                              <b className={cn('block truncate', ligado && 'text-foreground')}>{primeiro(p.nome)}</b>
                              <span className="block truncate text-xs text-muted-foreground">
                                {p.motivo ? p.motivo : p.pendentes ? `${num(p.pendentes)} pendentes agora` : 'sem carga agora'}
                                {p.com > 0 && ` · está com ${num(p.com)} destas`}
                              </span>
                            </span>
                          </label>
                        </td>
                        <td className="px-2 py-2">
                          <Input type="number" min={0} max={100} step={1} className="h-8 text-[13px]" disabled={!podeMarcar} value={ligado ? pct(peso) : ''} placeholder="0" onChange={(e) => setPesos((x) => ({ ...x, [p.conta]: Math.max(0, (Number(e.target.value) * total) / 100) }))} aria-label={`Porcentagem de ${p.nome}`} />
                        </td>
                        <td className="px-2 py-2">
                          <Input type="number" min={0} max={total} step={1} className="h-8 text-[13px]" disabled={!podeMarcar} value={ligado ? Math.round(peso) : ''} placeholder="0" onChange={(e) => setPesos((x) => ({ ...x, [p.conta]: Math.max(0, Number(e.target.value)) }))} aria-label={`Amostras de ${p.nome}`} />
                        </td>
                        <td className="py-2 pr-3 pl-2 text-[13px]">
                          {r ? (
                            <>
                              <b className="tab">{plural(r.total, 'amostra', 'amostras')}</b>
                              {(r.recebe > 0 || r.perde > 0) && (
                                <span className="text-xs text-muted-foreground">
                                  {' '}
                                  ({[r.recebe && `+${num(r.recebe)}`, r.perde && `−${num(r.perde)}`].filter(Boolean).join(' ')})
                                </span>
                              )}
                              <span className="block truncate text-xs text-muted-foreground" title={elementos.map((e) => `${e.elemento}: ${num(r.por_elemento[e.id_atividade] ?? 0)}`).join('\n')}>
                                {elementos.map((e) => `${e.elemento} ${num(r.por_elemento[e.id_atividade] ?? 0)}`).join(' · ')}
                              </span>
                            </>
                          ) : (
                            <span className="text-muted-foreground">{ligado ? '…' : '—'}</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {foraDaEquipe.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Não podem avaliar estas folhas: {foraDaEquipe.map((p) => `${primeiro(p.nome)} (${p.motivo})`).join('; ')}.
              </p>
            )}
            {dados.fora.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Ficam de fora: {dados.fora.map((f) => `${f.folha_revisao ?? `folha ${f.id_lote}`} (${f.motivo})`).join('; ')}.
              </p>
            )}
          </>
        )}
        <DialogFooter className="items-center gap-3 sm:justify-between">
          <span className={cn('text-[13px] text-muted-foreground', erroPrevia && 'text-[#8A5300]')}>
            {erroPrevia ??
              (!Object.keys(marcados).length
                ? 'Marque ao menos um avaliador.'
                : [
                    Math.round(soma) !== total && `Os pesos somam ${num(Math.round(soma))} de ${num(total)}: o Feixe reparte na proporção.`,
                    previa && (previa.movidas ? `${plural(previa.movidas, 'amostra muda', 'amostras mudam')} de mão` : 'Nada muda com estes pesos.'),
                  ]
                    .filter(Boolean)
                    .join(' '))}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => fechar(false)}>
              Depois
            </Button>
            <Button onClick={distribuir} disabled={!previa || !previa.movidas || !!erroPrevia || ocupado}>
              <RotuloEstavel ocupado={ocupado} rotulo="Distribuir" rotuloOcupado="Distribuindo…" />
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
