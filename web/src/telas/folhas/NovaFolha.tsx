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
import { comCargas, resumoPreparo } from './preparo'

type Escolhida = Pick<Folha, 'id' | 'cd_mi'> & { nm_carta?: string | null }

export function resumoCriacao(r: ResultadoCriacao) {
  const criadas = r.criados.map((c) => c.cd_mi ?? c.nome).join(', ')
  const ja = r.existentes.map((e) => e.cd_mi).join(', ')
  return [criadas && `Criadas em ${r.tema}: ${criadas}.`, ja && `Já existiam: ${ja}.`, resumoPreparo(r.preparo)].filter(Boolean).join(' ')
}

// Lotes criados que já têm cargas: são os que vão para o Distribuir.
export function criadosComCargas(r: ResultadoCriacao) {
  const prontas = comCargas(r.preparo)
  return r.criados.filter((c) => c.id_lote_etapa && prontas.has(c.id_lote_etapa)).map((c) => c.id_lote)
}

// Criar folhas: fluxo + uma ou várias folhas 1:100.000, achadas pela busca ou pelo clique no mapa do QGIS (B3). As
// cargas da primeira etapa saem junto (D-109), e quem abriu o diálogo recebe os lotes com cargas para distribuir.
export function NovaFolha({ aberto, fechar: fecharDialogo, fluxoInicial = null }: { aberto: boolean; fechar: (criados?: number[]) => void; fluxoInicial?: number | null }) {
  const avisar = useAvisar()
  const { ultimo, conectado } = useSessao()
  const [fluxo, setFluxo] = useState<number | null>(fluxoInicial)
  useEffect(() => {
    if (aberto && fluxoInicial) setFluxo(fluxoInicial)
  }, [aberto, fluxoInicial])
  const [busca, setBusca] = useState('')
  const [achadas, setAchadas] = useState<Folha[]>([])
  const [escolhidas, setEscolhidas] = useState<Escolhida[]>([])
  const [ocupado, setOcupado] = useState(false)
  // A malha de folhas está no mapa do QGIS e a ferramenta de escolher está ligada.
  const [noMapa, setNoMapa] = useState(false)

  const adicionar = (f: Escolhida) => setEscolhidas((xs) => (xs.some((x) => x.id === f.id) ? xs : [...xs, f]))

  // Folhas escolhidas ou tiradas no mapa do QGIS chegam pelo evento qgis {acao: "folhas", adicionar, tirar}.
  useEffect(() => {
    if (!aberto || ultimo?.evento !== 'qgis' || ultimo.dados.acao !== 'folhas') return
    const novas = (ultimo.dados.adicionar ?? []) as Escolhida[]
    const tirar = new Set((ultimo.dados.tirar ?? []) as number[])
    setEscolhidas((xs) => [...xs.filter((x) => !tirar.has(x.id)), ...novas.filter((n) => !xs.some((x) => x.id === n.id))])
  }, [ultimo, aberto])

  // A malha no QGIS acompanha a lista daqui (escolhidas pela busca ou tiradas no X) e o fluxo (o que já está no Feixe).
  useEffect(() => {
    if (noMapa) enviar('/api/qgis/folhas_escolhidas', { id_fluxo: fluxo, escolhidas: escolhidas.map((f) => f.id) }).catch(() => {})
  }, [noMapa, fluxo, escolhidas])

  function fechar(criados?: number[]) {
    if (noMapa) enviar('/api/qgis/folhas_fim').catch(() => {})
    setNoMapa(false)
    fecharDialogo(criados)
  }

  async function buscar() {
    try {
      setAchadas((await api<{ itens: Folha[] }>(`/api/folhas?limite=20&q=${encodeURIComponent(busca)}`)).itens)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  async function ligarMapa() {
    try {
      await enviar('/api/qgis/escolher_folhas', { id_fluxo: fluxo, escolhidas: escolhidas.map((f) => f.id) })
      setNoMapa(true)
      avisar('A malha de folhas está no QGIS: clique numa folha, ou Ctrl/Shift e arraste um retângulo.')
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  async function criar() {
    setOcupado(true)
    try {
      const r = await enviar<ResultadoCriacao>('/api/lotes', { tipo: 'folha', id_fluxo: fluxo, folhas: escolhidas.map((f) => f.id) })
      avisar(resumoCriacao(r), r.preparo?.erro ? 'erro' : undefined)
      setEscolhidas([])
      fechar(criadosComCargas(r))
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
          <DialogDescription>Cada folha entra na primeira etapa do fluxo, já com as cargas. Depois de criar, você distribui as folhas para a equipe.</DialogDescription>
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
            <Button type="button" variant="outline" onClick={ligarMapa} disabled={!conectado} title="Escolher no mapa do QGIS, com a malha de folhas">
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
        {noMapa && (
          <p className="text-[13px] text-muted-foreground">
            No QGIS: clique numa folha para escolher ou tirar; <b>Ctrl ou Shift e arraste</b> para escolher todas as folhas de um retângulo. Em azul, as escolhidas; hachuradas, as que já estão no Feixe{fluxo ? ' neste tema' : ' na sua unidade'}.
          </p>
        )}
        {escolhidas.length > 0 && (
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">
              {escolhidas.length === 1 ? '1 folha escolhida' : `${escolhidas.length} folhas escolhidas`}
            </span>
            <Button variant="ghost" size="sm" onClick={() => setEscolhidas([])}>
              Tirar todas
            </Button>
          </div>
        )}
        <div className="flex max-h-48 min-h-9 flex-wrap content-start gap-2 overflow-y-auto">
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
          <Button variant="outline" onClick={() => fechar()}>
            Cancelar
          </Button>
          <Button onClick={criar} disabled={!fluxo || escolhidas.length === 0 || ocupado}>
            {ocupado ? 'Criando e gerando as cargas…' : escolhidas.length > 1 ? `Criar ${escolhidas.length} folhas e gerar as cargas` : 'Criar a folha e gerar as cargas'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
