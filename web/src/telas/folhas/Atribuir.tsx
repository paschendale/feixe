import { useEffect, useState } from 'react'
import { Shuffle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { Lote, Pessoa, ResultadoAtribuicao } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { num } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

function Chips({ equipe, marcadas, mudar }: { equipe: Pessoa[]; marcadas: string[]; mudar: (x: string[]) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {equipe.map((p) => {
        const on = marcadas.includes(p.conta)
        return (
          <button
            key={p.conta}
            onClick={() => mudar(on ? marcadas.filter((x) => x !== p.conta) : [...marcadas, p.conta])}
            className={cn('h-8 rounded-full border px-3 text-sm', on ? 'border-ibge bg-ibge text-white' : 'bg-background hover:bg-accent')}
            title={`${p.pendentes} pendentes em ${p.folhas} folhas`}
          >
            {p.nome.split(' ').slice(0, 2).join(' ')}
          </button>
        )
      })}
    </div>
  )
}

function embaralhar<T>(xs: T[]) {
  const a = [...xs]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

// Atribuir (B5, passo 3 do planejamento): folha inteira com sorteio, dividir uma folha em blocos ou a seleção do
// QGIS. Tudo é sugestão até aplicar; a atribuição não muda a etapa da folha.
// Sugestão (D-72: sorteio e sugestão, nunca automático): cada folha, da que tem mais cargas a atribuir para a de menos,
// vai para quem estiver com menos pendentes naquele momento.
function sugerir(lotes: Lote[], equipe: Pessoa[], aAtribuir: Record<number, number>) {
  const carga = new Map(equipe.map((p) => [p.conta, p.pendentes]))
  const por: Record<number, string> = {}
  for (const l of [...lotes].sort((a, b) => (aAtribuir[b.id] ?? 0) - (aAtribuir[a.id] ?? 0))) {
    if (!aAtribuir[l.id]) continue
    const [conta] = [...carga].sort((a, b) => a[1] - b[1])[0] ?? []
    if (!conta) break
    por[l.id] = conta
    carga.set(conta, (carga.get(conta) ?? 0) + aAtribuir[l.id])
  }
  return por
}

export function Atribuir({ lotes, fechar, aAtribuir = {} }: { lotes: Lote[]; fechar: (feito: boolean) => void; aAtribuir?: Record<number, number> }) {
  const { eu } = useSessao()
  const [todas, setTodas] = useState(false)
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const aberto = lotes.length > 0
  // Só quem tem perfil de execução no projeto das folhas (a atribuição exige isso).
  const { dados } = useApi<{ itens: Pessoa[] }>(aberto ? `/api/equipe?projeto=${lotes[0].cod_projeto}` : null)
  const equipe = dados?.itens ?? []
  const nome = (c: string) => equipe.find((p) => p.conta === c)?.nome ?? c
  const [por, setPor] = useState<Record<number, string>>({})
  const [sorteio, setSorteio] = useState<string[]>([])
  const [soDisp, setSoDisp] = useState(true)
  const [dividir, setDividir] = useState<{ le: number | null; pessoas: string[]; plano: { conta: string; cargas: number }[] | null }>({ le: null, pessoas: [], plano: null })
  const [selecao, setSelecao] = useState<{ ids: number[]; camadas: string[] } | null>(null)
  const [destino, setDestino] = useState('')
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => {
    setPor(sugerir(lotes, equipe, aAtribuir))
    setDividir({ le: lotes[0]?.id_lote_etapa_atual ?? null, pessoas: [], plano: null })
    setSelecao(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotes, dados])

  function sortear() {
    const ordem = embaralhar(sorteio)
    const novo: Record<number, string> = {}
    embaralhar(lotes).forEach((l, i) => (novo[l.id] = ordem[i % ordem.length]))
    setPor(novo)
  }

  async function aplicar(fn: () => Promise<number>) {
    setOcupado(true)
    try {
      const n = await fn()
      avisar(`${num(n)} cargas atribuídas.`)
      fechar(true)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  const depois = new Map(equipe.map((p) => [p.conta, p.pendentes]))
  for (const l of lotes) if (por[l.id] && por[l.id] !== '-') depois.set(por[l.id], (depois.get(por[l.id]) ?? 0) + (aAtribuir[l.id] ?? 0))
  const totalAtribuir = lotes.reduce((s, l) => s + (por[l.id] && por[l.id] !== '-' ? aAtribuir[l.id] ?? 0 : 0), 0)
  const maxDepois = Math.max(1, ...depois.values())
  // Primeiro quem ganha cargas nesta atribuição; depois a equipe por pendentes, de quem tem menos para quem tem mais.
  const ganho = (p: Pessoa) => (depois.get(p.conta) ?? 0) - p.pendentes
  const pessoasOrdem = [...equipe].sort((a, b) => Number(ganho(b) > 0) - Number(ganho(a) > 0) || (depois.get(a.conta) ?? 0) - (depois.get(b.conta) ?? 0))
  const rotuloPessoa = (p: Pessoa) => `${p.nome}${p.conta === eu?.conta ? ' (você)' : ''}`

  const porFolha = () =>
    aplicar(async () => {
      let n = 0
      for (const l of lotes) {
        if (!por[l.id] || !l.id_lote_etapa_atual) continue
        const r = await enviar<ResultadoAtribuicao>('/api/cargas/atribuir', {
          lote_etapas: [l.id_lote_etapa_atual],
          responsavel: por[l.id] === '-' ? null : por[l.id],
          so_disponiveis: soDisp,
        })
        n += r.atribuidas
      }
      return n
    })

  async function previaDividir(pessoas: string[]) {
    setDividir((d) => ({ ...d, pessoas, plano: null }))
    if (!pessoas.length || !dividir.le) return
    try {
      const r = await enviar<{ plano: { conta: string; cargas: number }[] }>('/api/cargas/dividir', { id_lote_etapa: dividir.le, pessoas, previa: true })
      setDividir((d) => ({ ...d, pessoas, plano: r.plano }))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  return (
    <Dialog open={aberto} onOpenChange={(v) => !v && fechar(false)}>
      <DialogContent className="max-w-[880px]">
        <DialogHeader>
          <DialogTitle>Atribuir cargas</DialogTitle>
          <DialogDescription>
            {lotes.length === 1 ? lotes[0].folha_revisao : `${lotes.length} folhas marcadas`}
            {Object.keys(aAtribuir).length ? `, ${num(lotes.reduce((s, l) => s + (aAtribuir[l.id] ?? 0), 0))} cargas a atribuir` : ''}. Só cargas pendentes de etapas abertas mudam de mão; as concluídas ficam com quem as fez.
          </DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="folha">
          <TabsList>
            <TabsTrigger value="folha">Uma pessoa por folha</TabsTrigger>
            <TabsTrigger value="dividir">Dividir uma folha entre várias</TabsTrigger>
            <TabsTrigger value="qgis">Seleção do QGIS</TabsTrigger>
          </TabsList>

          <TabsContent value="folha" className="flex flex-col gap-3">
            <p className="text-sm text-[#3D4B5C]">O Feixe sugere quem tem menos pendentes no projeto. Mude à mão o que quiser, ou sorteie entre as pessoas marcadas.</p>
            <div className="flex flex-wrap items-start gap-5">
              <div className="max-h-72 min-w-[340px] flex-[3_1_420px] overflow-auto rounded-md border">
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="text-left text-xs text-muted-foreground">
                      <th className="border-b px-3 py-2 font-medium">Folha</th>
                      {Object.keys(aAtribuir).length > 0 && <th className="border-b px-2 py-2 text-right font-medium">A atribuir</th>}
                      <th className="border-b px-3 py-2 font-medium">Para quem</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lotes.map((l) => (
                      <tr key={l.id} className="border-b last:border-0">
                        <td className="tab px-3 py-1.5 font-semibold whitespace-nowrap">{l.folha_revisao}</td>
                        {Object.keys(aAtribuir).length > 0 && <td className="tab px-2 py-1.5 text-right">{num(aAtribuir[l.id] ?? 0)}</td>}
                        <td className="px-3 py-1.5">
                          <Select className="h-8" value={por[l.id] ?? ''} onChange={(e) => setPor({ ...por, [l.id]: e.target.value })} aria-label={`Para quem, ${l.folha_revisao}`}>
                            <option value="">Não mudar</option>
                            <option value="-">Ninguém: volta a atribuir (tirar de quem está)</option>
                            {equipe.map((p) => (
                              <option key={p.conta} value={p.conta}>
                                {rotuloPessoa(p)} · {num(p.pendentes)} pendentes
                              </option>
                            ))}
                          </Select>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="flex min-w-[260px] flex-[2_1_280px] flex-col gap-2">
                <span className="text-xs text-muted-foreground">Equipe por pendentes{totalAtribuir ? ' (depois da atribuição)' : ''}</span>
                {(todas ? pessoasOrdem : pessoasOrdem.slice(0, 6)).map((p) => {
                  const antes = p.pendentes
                  const dep = depois.get(p.conta) ?? antes
                  return (
                    <div key={p.conta} className="grid grid-cols-[120px_1fr_auto] items-center gap-2 text-[13px]">
                      <span className="truncate" title={p.nome}>
                        {rotuloPessoa(p)}
                      </span>
                      <span className="flex h-1.5 overflow-hidden rounded-sm bg-border">
                        <span className="h-full bg-aco" style={{ width: `${(100 * antes) / maxDepois}%` }} />
                        <span className="h-full bg-ibge" style={{ width: `${(100 * (dep - antes)) / maxDepois}%` }} />
                      </span>
                      <span className="tab text-right text-muted-foreground">{dep !== antes ? `${num(antes)} → ${num(dep)}` : num(antes)}</span>
                    </div>
                  )
                })}
                {pessoasOrdem.length > 6 && (
                  <button className="self-start text-[13px] text-ibge hover:underline" onClick={() => setTodas(!todas)}>
                    {todas ? 'Ver menos' : `Ver as ${pessoasOrdem.length} pessoas`}
                  </button>
                )}
              </div>
            </div>
            <div className="flex items-start gap-3 border-t pt-3">
              <div className="flex-1">
                <span className="mb-1.5 block text-xs text-muted-foreground">Sortear entre:</span>
                <Chips equipe={equipe} marcadas={sorteio} mudar={setSorteio} />
              </div>
              <Button size="sm" variant="outline" disabled={!sorteio.length} onClick={sortear}>
                <Shuffle /> Sortear
              </Button>
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={soDisp} onChange={(e) => setSoDisp(e.target.checked)} /> Só as cargas a atribuir (não tirar de quem já tem)
            </label>
            <DialogFooter>
              <Button variant="outline" onClick={() => fechar(false)}>
                Cancelar
              </Button>
              <Button onClick={porFolha} disabled={ocupado || !Object.values(por).some(Boolean)}>
                {totalAtribuir && soDisp ? `Atribuir ${num(totalAtribuir)} cargas` : 'Atribuir'}
              </Button>
            </DialogFooter>
          </TabsContent>

          <TabsContent value="dividir" className="flex flex-col gap-3">
            <Select value={dividir.le ?? ''} onChange={(e) => setDividir({ le: Number(e.target.value), pessoas: [], plano: null })} aria-label="Folha">
              {lotes.map((l) => (
                <option key={l.id} value={l.id_lote_etapa_atual ?? ''}>
                  {l.folha_revisao} · {l.tema} · {l.etapa}
                </option>
              ))}
            </Select>
            <Chips equipe={equipe} marcadas={dividir.pessoas} mudar={previaDividir} />
            {dividir.plano && (
              <p className="text-sm">
                {dividir.plano.map((p) => `${nome(p.conta).split(' ')[0]}: ${p.cargas}`).join(' · ')}{' '}
                <span className="text-muted-foreground">(cargas a atribuir em faixas de norte a sul)</span>
              </p>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={() => fechar(false)}>
                Cancelar
              </Button>
              <Button
                disabled={ocupado || !dividir.plano}
                onClick={() =>
                  aplicar(async () => {
                    await enviar('/api/cargas/dividir', { id_lote_etapa: dividir.le, pessoas: dividir.pessoas, previa: false })
                    return dividir.plano!.reduce((s, p) => s + p.cargas, 0)
                  })
                }
              >
                Aplicar
              </Button>
            </DialogFooter>
          </TabsContent>

          <TabsContent value="qgis" className="flex flex-col gap-3">
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                disabled={!conectado}
                onClick={() =>
                  enviar<{ ids: number[]; camadas: string[] }>('/api/qgis/selecao_cargas')
                    .then(setSelecao)
                    .catch((e) => avisar((e as Error).message, 'erro'))
                }
              >
                Ler a seleção do QGIS
              </Button>
              <span className="text-sm text-muted-foreground">
                {selecao ? `${num(selecao.ids.length)} cargas selecionadas${selecao.camadas.length ? ` em ${selecao.camadas.join(', ')}` : ''}` : 'Selecione cargas no mapa, nas camadas do Feixe.'}
              </span>
            </div>
            <Select value={destino} onChange={(e) => setDestino(e.target.value)} aria-label="Para quem">
              <option value="">Para quem?</option>
              <option value="-">Ninguém: volta a atribuir (tirar de quem está)</option>
              {equipe.map((p) => (
                <option key={p.conta} value={p.conta}>
                  {p.nome}
                </option>
              ))}
            </Select>
            <DialogFooter>
              <Button variant="outline" onClick={() => fechar(false)}>
                Cancelar
              </Button>
              <Button
                disabled={ocupado || !selecao?.ids.length || !destino}
                onClick={() =>
                  aplicar(async () => (await enviar<ResultadoAtribuicao>('/api/cargas/atribuir', { ids: selecao!.ids, responsavel: destino === '-' ? null : destino })).atribuidas)
                }
              >
                Aplicar
              </Button>
            </DialogFooter>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
