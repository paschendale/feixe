import { useEffect, useState } from 'react'
import { MousePointerClick, Search, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api, type Folha, type ResultadoCriacao } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { useSessao } from '@/lib/sessao'
import { enviar } from '@/lib/useApi'
import { EscolherFluxo } from './EscolherFluxo'

type Escolhida = Pick<Folha, 'id' | 'cd_mi'> & { nm_carta?: string | null }

export function resumoCriacao(r: ResultadoCriacao) {
  const criadas = r.criados.map((c) => c.cd_mi ?? c.nome).join(', ')
  const ja = r.existentes.map((e) => e.cd_mi).join(', ')
  return [criadas && `Criadas em ${r.tema}: ${criadas}.`, ja && `Já existiam: ${ja}.`].filter(Boolean).join(' ')
}

// Criar folhas: fluxo + uma ou várias folhas 1:100.000, achadas pela busca ou pelo clique no mapa do QGIS (B3).
export function NovaFolha({ aberto, fechar }: { aberto: boolean; fechar: () => void }) {
  const avisar = useAvisar()
  const { ultimo, conectado } = useSessao()
  const [fluxo, setFluxo] = useState<number | null>(null)
  const [busca, setBusca] = useState('')
  const [achadas, setAchadas] = useState<Folha[]>([])
  const [escolhidas, setEscolhidas] = useState<Escolhida[]>([])
  const [ocupado, setOcupado] = useState(false)

  const adicionar = (f: Escolhida) => setEscolhidas((xs) => (xs.some((x) => x.id === f.id) ? xs : [...xs, f]))

  // Folha clicada no mapa do QGIS chega pelo evento qgis {acao: "folha"}.
  useEffect(() => {
    if (aberto && ultimo?.evento === 'qgis' && ultimo.dados.acao === 'folha') adicionar(ultimo.dados.folha as Escolhida)
  }, [ultimo, aberto])

  async function buscar() {
    try {
      setAchadas((await api<{ itens: Folha[] }>(`/api/folhas?limite=20&q=${encodeURIComponent(busca)}`)).itens)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  async function noMapa() {
    try {
      await enviar('/api/qgis/escolher_folhas')
      avisar('Clique nas folhas no mapa do QGIS; elas aparecem aqui.')
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  async function criar() {
    setOcupado(true)
    try {
      const r = await enviar<ResultadoCriacao>('/api/lotes', { tipo: 'folha', id_fluxo: fluxo, folhas: escolhidas.map((f) => f.id) })
      avisar(resumoCriacao(r))
      setEscolhidas([])
      fechar()
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <Dialog open={aberto} onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Novas folhas</DialogTitle>
          <DialogDescription>Cada folha entra na primeira etapa do fluxo, a iniciar.</DialogDescription>
        </DialogHeader>
        <EscolherFluxo valor={fluxo} mudar={(f) => setFluxo(f?.id ?? null)} />
        <div className="grid gap-1.5">
          <Label htmlFor="busca-folha">Folhas 1:100.000</Label>
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              buscar()
            }}
          >
            <Input id="busca-folha" placeholder="MI, nome ou nomenclatura (ex.: 2534)" value={busca} onChange={(e) => setBusca(e.target.value)} />
            <Button type="submit" variant="outline">
              <Search /> Buscar
            </Button>
            <Button type="button" variant="outline" onClick={noMapa} disabled={!conectado} title="Escolher clicando no mapa do QGIS">
              <MousePointerClick /> No mapa
            </Button>
          </form>
          {achadas.length > 0 && (
            <ul className="max-h-40 divide-y overflow-auto rounded-md border text-sm">
              {achadas.map((f) => (
                <li key={f.id}>
                  <button className="flex w-full justify-between px-3 py-1.5 text-left hover:bg-accent" onClick={() => adicionar(f)}>
                    <span>
                      <b className="tab">{f.cd_mi}</b>
                      {f.nm_carta ? ` · ${f.nm_carta}` : ''}
                    </span>
                    <span className="text-muted-foreground">{f.nomenclatura}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="flex min-h-9 flex-wrap gap-2">
          {escolhidas.length === 0 && <p className="text-sm text-muted-foreground">Nenhuma folha escolhida.</p>}
          {escolhidas.map((f) => (
            <span key={f.id} className="inline-flex h-8 items-center gap-1.5 rounded-full bg-ibge pr-1.5 pl-3 text-sm text-white">
              <b className="tab">{f.cd_mi}</b>
              <button aria-label={`Tirar ${f.cd_mi}`} onClick={() => setEscolhidas((xs) => xs.filter((x) => x.id !== f.id))}>
                <X className="size-3.5" />
              </button>
            </span>
          ))}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={fechar}>
            Cancelar
          </Button>
          <Button onClick={criar} disabled={!fluxo || escolhidas.length === 0 || ocupado}>
            {ocupado ? 'Criando…' : escolhidas.length > 1 ? `Criar ${escolhidas.length} folhas` : 'Criar folha'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
