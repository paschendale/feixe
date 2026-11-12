import { useEffect } from 'react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { AvisosProvider } from '@/lib/avisos'
import { navegar, useRota } from '@/lib/rotas'
import { SessaoProvider, useSessao } from '@/lib/sessao'
import { cn } from '@/lib/utils'
import { telasDe } from '@/telas'

function Casca() {
  const { status, eu, conectado } = useSessao()
  const rota = useRota()
  const telas = telasDe(eu?.papeis ?? [])
  const atual = telas.find((t) => t.id === rota.tela)

  // Sem tela no endereço (ou tela que o papel não vê): vai para a primeira do menu.
  useEffect(() => {
    if (!atual && telas.length) navegar(telas[0].id)
  }, [atual, telas])

  const Componente = atual?.componente
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r bg-muted/30 p-3">
        <div className="mb-4 px-2 text-xl font-semibold">Feixe</div>
        <nav className="flex flex-col gap-1">
          {telas.map((t) => (
            <a
              key={t.id}
              href={`#/${t.id}`}
              className={cn(
                'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm hover:bg-accent',
                t.id === atual?.id && 'bg-accent font-medium',
              )}
            >
              <t.icone className="size-4" />
              {t.rotulo}
            </a>
          ))}
        </nav>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b px-6 py-3">
          <h1 className="text-lg font-semibold">{atual?.rotulo}</h1>
          <div className="flex items-center gap-2">
            {eu && (
              <span className="text-right text-sm leading-tight" title={eu.conta}>
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
        <main className="space-y-4 p-6">
          {!conectado && (
            <Card className="border-destructive">
              <CardContent className="pt-6 text-sm">O QGIS fechou ou o plugin foi descarregado. Reabra o Feixe pelo QGIS.</CardContent>
            </Card>
          )}
          {Componente && <Componente />}
        </main>
      </div>
    </div>
  )
}

export default function App() {
  return (
    <SessaoProvider>
      <AvisosProvider>
        <Casca />
      </AvisosProvider>
    </SessaoProvider>
  )
}
