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
export function Atribuir({ lotes, fechar }: { lotes: Lote[]; fechar: (feito: boolean) => void }) {
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
    setPor({})
    setDividir({ le: lotes[0]?.id_lote_etapa_atual ?? null, pessoas: [], plano: null })
    setSelecao(null)
  }, [lotes])

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
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Atribuir cargas</DialogTitle>
          <DialogDescription>Só cargas pendentes de etapas abertas mudam de mão; as concluídas ficam com quem as fez.</DialogDescription>
        </DialogHeader>
        <Tabs defaultValue="folha">
          <TabsList>
            <TabsTrigger value="folha">Folha inteira</TabsTrigger>
            <TabsTrigger value="dividir">Dividir uma folha</TabsTrigger>
            <TabsTrigger value="qgis">Seleção do QGIS</TabsTrigger>
          </TabsList>

          <TabsContent value="folha" className="flex flex-col gap-3">
            <div className="flex items-start gap-3">
              <div className="flex-1">
                <Chips equipe={equipe} marcadas={sorteio} mudar={setSorteio} />
              </div>
              <Button size="sm" variant="outline" disabled={!sorteio.length} onClick={sortear}>
                <Shuffle /> {Object.keys(por).length ? 'Sortear de novo' : 'Sortear'}
              </Button>
            </div>
            <div className="max-h-64 overflow-auto rounded-md border">
              {lotes.map((l) => (
                <div key={l.id} className="flex items-center gap-3 border-b px-3 py-1.5 last:border-0">
                  <b className="tab w-20">{l.folha_revisao}</b>
                  <span className="flex-1 truncate text-sm text-muted-foreground">
                    {l.tema} · {l.etapa}
                  </span>
                  <Select className="h-8 w-60" value={por[l.id] ?? ''} onChange={(e) => setPor({ ...por, [l.id]: e.target.value })} aria-label={`Responsável por ${l.folha_revisao}`}>
                    <option value="">Não mudar</option>
                    <option value="-">Ninguém: volta a atribuir (tirar de quem está)</option>
                    {equipe.map((p) => (
                      <option key={p.conta} value={p.conta}>
                        {p.nome}
                      </option>
                    ))}
                  </Select>
                </div>
              ))}
            </div>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={soDisp} onChange={(e) => setSoDisp(e.target.checked)} /> Só as cargas a atribuir (não tirar de quem já tem)
            </label>
            <DialogFooter>
              <Button variant="outline" onClick={() => fechar(false)}>
                Cancelar
              </Button>
              <Button onClick={porFolha} disabled={ocupado || !Object.values(por).some(Boolean)}>
                Aplicar
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
