import { useEffect, useMemo, useRef, useState } from 'react'
import { Colunas, RotuloEstavel } from '@/components/painel'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import type { ResultadoDistribuicaoCQ, SugestaoDistribuicaoCQ } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { lista, num, plural } from '@/lib/formato'
import { enviar } from '@/lib/useApi'
import { cn } from '@/lib/utils'

type Pessoa = SugestaoDistribuicaoCQ['pessoas'][number]
const primeiro = (n: string | null | undefined) => (n ?? '').split(' ').slice(0, 2).join(' ')
const folhasTxt = (fs: string[]) => (fs.length <= 6 ? lista(fs) : `${lista(fs.slice(0, 5))} e mais ${num(fs.length - 5)}`)
const iguais = (contas: string[], total: number) => Object.fromEntries(contas.map((c) => [c, total / Math.max(1, contas.length)]))

// Distribuir as amostras de CQ (D-147). No CQ várias pessoas avaliam a mesma folha: as amostras das folhas escolhidas
// se juntam e se repartem entre os avaliadores escolhidos, na proporção do peso de cada um (em % ou em amostras, a
// mesma coisa vista de dois jeitos), com uma fatia de cada elemento para cada um. Sem fila: recebem agora e a etapa de
// CQ começa. O diálogo começa pela pergunta: a equipe do último CQ desta etapa (ou a que já está com as folhas), para
// reutilizar ou trocar; sem nenhuma, vai direto à escolha. Quem executou a folha não avalia (regra fixa).
export function DistribuirCQ({ lotes, fechar }: { lotes: number[]; fechar: (feito: boolean) => void }) {
  const avisar = useAvisar()
  const [dados, setDados] = useState<SugestaoDistribuicaoCQ | null>(null)
  const [pergunta, setPergunta] = useState(false)
  const [pesos, setPesos] = useState<Record<string, number>>({})
  const [previa, setPrevia] = useState<ResultadoDistribuicaoCQ | null>(null)
  const [erroPrevia, setErroPrevia] = useState<string | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const pedido = useRef(0)
  const chave = lotes.join(',')

  useEffect(() => {
    if (!chave) return
    let vivo = true
    setDados(null)
    setPrevia(null)
    enviar<SugestaoDistribuicaoCQ>('/api/distribuir_cq/sugestao', { lotes: chave.split(',').map(Number) })
      .then((d) => {
        if (!vivo) return
        setDados(d)
        const sugeridos = d.pessoas.filter((p) => p.peso > 0)
        setPergunta(sugeridos.length > 0)
        setPesos(d.origem === 'atual' ? Object.fromEntries(sugeridos.map((p) => [p.conta, p.peso])) : {})
      })
      .catch((e) => vivo && avisar((e as Error).message, 'erro'))
    return () => {
      vivo = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave])

  const escolhidos = useMemo(() => Object.keys(pesos), [pesos])
  const validos = useMemo(() => Object.fromEntries(Object.entries(pesos).filter(([, p]) => p > 0)), [pesos])
  const total = dados?.total ?? 0
  const soma = Object.values(validos).reduce((a, b) => a + b, 0)

  // A prévia vem do servidor (a mesma conta que grava), um instante depois da última mudança.
  useEffect(() => {
    if (!dados || !total || pergunta) return
    if (!Object.keys(validos).length) {
      setPrevia(null)
      setErroPrevia(null)
      return
    }
    const n = ++pedido.current
    const t = window.setTimeout(() => {
      enviar<ResultadoDistribuicaoCQ>('/api/distribuir_cq', { lotes: chave.split(',').map(Number), pesos: validos, previa: true })
        .then((r) => {
          if (n !== pedido.current) return
          setPrevia(r)
          setErroPrevia(null)
        })
        .catch((e) => n === pedido.current && setErroPrevia((e as Error).message))
    }, 250)
    return () => window.clearTimeout(t)
  }, [dados, total, pergunta, validos, chave])

  const porConta = useMemo(() => new Map((dados?.pessoas ?? []).map((p) => [p.conta, p])), [dados])
  const doServidor = useMemo(() => new Map((previa?.pessoas ?? []).map((p) => [p.conta, p])), [previa])
  const sugeridos = (dados?.pessoas ?? []).filter((p) => p.peso > 0)
  const paraAdicionar = (dados?.pessoas ?? []).filter((p) => !(p.conta in pesos))
  const elementos = dados?.elementos ?? []
  const pct = (p: number) => (total ? Math.round((1000 * p) / total) / 10 : 0)

  function reutilizar() {
    setPesos(Object.fromEntries(sugeridos.map((p) => [p.conta, p.peso])))
    setPergunta(false)
  }
  function outras() {
    setPesos({})
    setPergunta(false)
  }
  function adicionar(conta: string) {
    if (!conta) return
    // Quem entra divide em partes iguais com os que já estão; o supervisor ajusta depois.
    setPesos((x) => iguais([...Object.keys(x), conta], total))
  }
  function tirar(conta: string) {
    setPesos((x) => {
      const { [conta]: _, ...resto } = x
      return resto
    })
  }

  async function distribuir() {
    setOcupado(true)
    try {
      const r = await enviar<ResultadoDistribuicaoCQ>('/api/distribuir_cq', { lotes, pesos: validos, previa: false })
      const quem = r.pessoas.filter((p) => p.total > p.avaliadas).map((p) => `${primeiro(p.nome)} (${num(p.total - p.avaliadas)})`)
      avisar(`Amostras distribuídas: ${plural(r.movidas, 'mudou de mão', 'mudaram de mão')}. A avaliar com cada um: ${lista(quem)}. A etapa de CQ começou.`)
      fechar(true)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  const nFolhas = dados?.folhas.length ?? lotes.length
  const avaliadas = (dados?.folhas ?? []).reduce((n, f) => n + f.avaliadas, 0)
  const nomes = (ps: Pessoa[]) => lista(ps.map((p) => `${primeiro(p.nome)} (${pct(p.peso)}%)`))
  return (
    <Dialog open={lotes.length > 0} onOpenChange={(v) => !v && fechar(false)}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Distribuir as amostras de {nFolhas === 1 && dados?.folhas[0] ? dados.folhas[0].folha_revisao : plural(nFolhas, 'folha', 'folhas')}</DialogTitle>
          <DialogDescription>
            As amostras {nFolhas > 1 ? 'das folhas se juntam e ' : ''}se repartem entre os avaliadores que você escolher, na proporção de cada um, com uma fatia de cada elemento para cada pessoa. Quem recebe começa agora, sem fila. Quem executou a folha não avalia.
          </DialogDescription>
        </DialogHeader>
        {!dados && <div className="grid h-[200px] place-items-center rounded-md border text-sm text-muted-foreground">Montando a sugestão…</div>}
        {dados && !total && <p className="text-sm text-muted-foreground">Nenhuma destas folhas tem amostras de CQ: os planos ainda não foram criados (gaveta da folha).</p>}
        {dados && total > 0 && (
          <p className="text-[13px] text-texto-2">
            <b className="text-foreground">{plural(total, 'amostra', 'amostras')}</b> em {folhasTxt(dados.folhas.map((f) => f.folha_revisao))}
            {avaliadas > 0 && `, ${num(avaliadas)} já avaliadas (ficam com quem avaliou)`} · {elementos.map((e) => `${e.elemento} ${num(e.amostras)}`).join(' · ')}
          </p>
        )}

        {dados && total > 0 && pergunta && (
          <div className="flex flex-col gap-3 rounded-lg bg-[#EEF3FA] px-4 py-3.5 text-sm text-[#1C2F4A]">
            <span>
              {dados.origem === 'atual' ? (
                <>
                  Estas folhas já estão com <b>{nomes(sugeridos)}</b>. Manter esta equipe e ajustar a divisão?
                </>
              ) : (
                <>
                  No último CQ desta etapa ({dados.origem_folha}) avaliaram <b>{nomes(sugeridos)}</b>. Reutilizar esta equipe, na mesma proporção?
                </>
              )}
            </span>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" className="font-semibold" onClick={reutilizar}>
                {dados.origem === 'atual' ? 'Manter e ajustar' : 'Reutilizar'}
              </Button>
              <Button size="sm" variant="outline" onClick={outras}>
                Escolher outras pessoas
              </Button>
            </div>
          </div>
        )}

        {dados && total > 0 && !pergunta && (
          <>
            {escolhidos.length > 0 ? (
              <div className="max-h-[42vh] overflow-auto rounded-md border">
                <table className="w-full table-fixed border-collapse text-sm">
                  <Colunas larguras={['30%', '12%', '14%', undefined, '40px']} />
                  <thead className="sticky top-0 bg-card">
                    <tr className="text-left text-xs text-muted-foreground">
                      <th className="border-b py-2 pr-2 pl-3 font-medium">Avaliador</th>
                      <th className="border-b px-2 py-2 font-medium">%</th>
                      <th className="border-b px-2 py-2 font-medium">Amostras</th>
                      <th className="border-b px-2 py-2 font-medium">Fica com</th>
                      <th className="border-b" />
                    </tr>
                  </thead>
                  <tbody>
                    {escolhidos.map((conta) => {
                      const p = porConta.get(conta)
                      const peso = pesos[conta] ?? 0
                      const r = doServidor.get(conta)
                      return (
                        <tr key={conta} className="border-b border-linha last:border-0">
                          <td className="py-2 pr-2 pl-3">
                            <b className="block truncate">{primeiro(p?.nome ?? conta)}</b>
                            <span className="block truncate text-xs text-muted-foreground">
                              {p?.pendentes ? `${num(p.pendentes)} pendentes agora` : 'sem carga agora'}
                              {p?.com ? ` · está com ${num(p.com)} destas` : ''}
                            </span>
                          </td>
                          <td className="px-2 py-2">
                            <Input type="number" min={0} max={100} step={1} className="h-8 text-[13px]" value={pct(peso)} onChange={(e) => setPesos((x) => ({ ...x, [conta]: Math.max(0, (Number(e.target.value) * total) / 100) }))} aria-label={`Porcentagem de ${p?.nome ?? conta}`} />
                          </td>
                          <td className="px-2 py-2">
                            <Input type="number" min={0} max={total} step={1} className="h-8 text-[13px]" value={Math.round(peso)} onChange={(e) => setPesos((x) => ({ ...x, [conta]: Math.max(0, Number(e.target.value)) }))} aria-label={`Amostras de ${p?.nome ?? conta}`} />
                          </td>
                          <td className="px-2 py-2 text-[13px]">
                            {r ? (
                              <>
                                <b className="tab">{plural(r.total, 'amostra', 'amostras')}</b>
                                {(r.recebe > 0 || r.perde > 0) && <span className="text-xs text-muted-foreground"> ({[r.recebe && `+${num(r.recebe)}`, r.perde && `−${num(r.perde)}`].filter(Boolean).join(' ')})</span>}
                                <span className="block truncate text-xs text-muted-foreground" title={elementos.map((e) => `${e.elemento}: ${num(r.por_elemento[e.id_atividade] ?? 0)}`).join('\n')}>
                                  {elementos.map((e) => `${e.elemento} ${num(r.por_elemento[e.id_atividade] ?? 0)}`).join(' · ')}
                                </span>
                              </>
                            ) : (
                              <span className="text-muted-foreground">{peso > 0 ? '…' : 'nada'}</span>
                            )}
                          </td>
                          <td className="pr-2 text-right">
                            <Button size="sm" variant="ghost" className="h-7 px-2 text-muted-foreground" onClick={() => tirar(conta)} aria-label={`Tirar ${p?.nome ?? conta}`} title="Tirar da divisão">
                              ×
                            </Button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="rounded-md border border-dashed px-3.5 py-3 text-[13px] text-muted-foreground">Escolha quem vai avaliar: cada pessoa que você adicionar divide as amostras em partes iguais com as outras, e depois você ajusta a proporção.</p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Select className="h-8 w-[320px] max-w-full text-[13px]" value="" onChange={(e) => adicionar(e.target.value)} aria-label="Adicionar avaliador">
                <option value="">Adicionar avaliador…</option>
                {paraAdicionar.map((p) => (
                  <option key={p.conta} value={p.conta} disabled={!!p.motivo}>
                    {primeiro(p.nome)} · {p.motivo ?? (p.pendentes ? `${num(p.pendentes)} pendentes` : 'sem carga')}
                  </option>
                ))}
              </Select>
              {escolhidos.length > 1 && (
                <Button size="sm" variant="outline" onClick={() => setPesos(iguais(escolhidos, total))}>
                  Partes iguais
                </Button>
              )}
              {dados.sem_perfil_v && <span className="text-xs text-muted-foreground">Ninguém tem perfil de avaliador (V) no projeto: a lista traz a equipe toda.</span>}
            </div>
            {dados.fora.length > 0 && <p className="text-xs text-muted-foreground">Ficam de fora: {dados.fora.map((f) => `${f.folha_revisao ?? `folha ${f.id_lote}`} (${f.motivo})`).join('; ')}.</p>}
          </>
        )}

        <DialogFooter className="items-center gap-3 sm:justify-between">
          <span className={cn('text-[13px] text-muted-foreground', erroPrevia && 'text-[#8A5300]')}>
            {pergunta || !dados || !total
              ? ''
              : (erroPrevia ??
                (!Object.keys(validos).length
                  ? 'Adicione ao menos um avaliador.'
                  : [Math.round(soma) !== total && `Os pesos somam ${num(Math.round(soma))} de ${num(total)}: o Feixe reparte na proporção.`, previa && (previa.movidas ? `${plural(previa.movidas, 'amostra muda', 'amostras mudam')} de mão.` : 'Nada muda com esta divisão.')].filter(Boolean).join(' ')))}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => fechar(false)}>
              Depois
            </Button>
            {!pergunta && (
              <Button onClick={distribuir} disabled={!previa || !previa.movidas || !!erroPrevia || ocupado}>
                <RotuloEstavel ocupado={ocupado} rotulo="Distribuir" rotuloOcupado="Distribuindo…" />
              </Button>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
