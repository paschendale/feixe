import { useCallback, useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { api, type Eu, type Folha, type Status } from '@/lib/api'
import { useEventos } from '@/lib/sse'

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [eu, setEu] = useState<Eu | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [folhas, setFolhas] = useState<Folha[]>([])
  const [busca, setBusca] = useState('')
  const [carregando, setCarregando] = useState(false)

  const carregarStatus = useCallback(() => {
    api<Status>('/api/status').then(setStatus).catch((e) => setErro(String(e.message)))
    // Sem banco ou sem credencial, o cabeçalho fica só com o ambiente; não é erro da tela.
    api<Eu>('/api/eu').then(setEu).catch(() => setEu(null))
  }, [])

  const { conectado } = useEventos(['estado', 'configuracao'], () => carregarStatus())

  useEffect(() => {
    carregarStatus()
  }, [carregarStatus])

  async function buscarFolhas() {
    setCarregando(true)
    setErro(null)
    try {
      const r = await api<{ itens: Folha[] }>(`/api/folhas?limite=50&q=${encodeURIComponent(busca)}`)
      setFolhas(r.itens)
    } catch (e) {
      setErro((e as Error).message)
    } finally {
      setCarregando(false)
    }
  }

  async function zoom(f: Folha) {
    try {
      await api(`/api/folhas/${f.id}/zoom`, { method: 'POST' })
    } catch (e) {
      setErro((e as Error).message)
    }
  }

  return (
    <main className="mx-auto max-w-5xl p-6 space-y-6">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Feixe</h1>
        <div className="flex items-center gap-2">
          {eu && (
            <span className="text-sm text-right leading-tight" title={eu.conta}>
              <span className="font-medium">{eu.nome}</span>
              <span className="block text-muted-foreground">
                {eu.papel_rotulo}
                {eu.uf ? ` · ${eu.uf}` : ''}
                {eu.equipe ? ` · ${eu.equipe}` : ''}
              </span>
            </span>
          )}
          {status && (
            <Badge style={{ background: status.cor_ambiente, color: 'white' }}>{status.rotulo_ambiente}</Badge>
          )}
          <Badge variant={conectado ? 'default' : 'destructive'}>{conectado ? 'QGIS conectado' : 'QGIS desconectado'}</Badge>
        </div>
      </header>

      {!conectado && (
        <Card className="border-destructive">
          <CardContent className="pt-6 text-sm">
            O QGIS fechou ou o plugin foi descarregado. Reabra o Feixe pelo QGIS.
          </CardContent>
        </Card>
      )}

      <section className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader><CardTitle className="text-sm">Banco</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            <div>{status?.online ? '● online' : '○ offline'}</div>
            <div className="text-muted-foreground">{status?.banco}</div>
            {status && !status.credencial && <div className="text-destructive">usuário e senha não configurados (dock do QGIS)</div>}
            <div className="text-muted-foreground">{status?.detalhe}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Usuário</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            <div>{eu?.nome ?? status?.usuario ?? 'desconhecido (informe usuário e senha no dock do QGIS)'}</div>
            {eu && (
              <div className="text-muted-foreground">
                {eu.conta} · {eu.uf ?? 'sem lotação'} · {eu.papeis.length ? eu.papeis.join(', ') : 'sem papel'}
              </div>
            )}
            {eu && !eu.elegivel && (
              <div className="text-destructive">conta inativa, de sistema ou super no SGBC: sem papel no Feixe</div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="text-sm">Versões</CardTitle></CardHeader>
          <CardContent className="text-sm space-y-1">
            <div>plugin {status?.versao_plugin}</div>
            <div className="text-muted-foreground">QGIS {status?.qgis}</div>
          </CardContent>
        </Card>
      </section>

      <Card>
        <CardHeader><CardTitle>Folhas 1:100.000</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              buscarFolhas()
            }}
          >
            <Input placeholder="MI, nome ou nomenclatura (ex.: 2534)" value={busca} onChange={(e) => setBusca(e.target.value)} />
            <Button type="submit" disabled={carregando}>{carregando ? 'Buscando…' : 'Buscar'}</Button>
          </form>
          {erro && <p className="text-sm text-destructive">{erro}</p>}
          <ul className="divide-y">
            {folhas.map((f) => (
              <li key={f.id} className="flex items-center justify-between py-2 text-sm">
                <span>
                  <span className="font-mono">{f.cd_mi}</span> · {f.nm_carta ?? '—'} · <span className="text-muted-foreground">{f.nomenclatura}</span>
                </span>
                <Button size="sm" variant="outline" onClick={() => zoom(f)} disabled={!conectado}>Zoom no QGIS</Button>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </main>
  )
}
