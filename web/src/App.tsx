import { useEffect, useState } from 'react'
import { Layers } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Logo } from '@/components/Logo'
import { AvisosProvider, useAvisar } from '@/lib/avisos'
import { navegar, useRota } from '@/lib/rotas'
import { SessaoProvider, useSessao } from '@/lib/sessao'
import { enviar } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { telasDe } from '@/telas'

// Monta (ou remonta) o grupo Feixe no projeto aberto do QGIS (B1).
function BotaoCamadas() {
  const avisar = useAvisar()
  const { conectado, eu } = useSessao()
  const [ocupado, setOcupado] = useState(false)
  if (!eu?.papeis.length) return null
  async function montar() {
    setOcupado(true)
    try {
      const r = await enviar<{ camadas: { nome: string; feicoes: number }[] }>('/api/camadas/montar')
      avisar('Camadas no QGIS: ' + r.camadas.map((c) => `${c.nome} (${c.feicoes})`).join(', '))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }
  return (
    <button
      onClick={montar}
      disabled={!conectado || ocupado}
      title="Monta o grupo Feixe no projeto aberto do QGIS"
      className="flex h-8 items-center gap-1.5 rounded-md px-2.5 text-white/85 hover:bg-white/10 hover:text-white disabled:opacity-40"
    >
      <Layers className="size-4" /> {ocupado ? 'Montando…' : 'Camadas no QGIS'}
    </button>
  )
}

// Primeiro e último nome: "Victor dos Santos Marotta" -> "VM".
function iniciais(nome: string) {
  const partes = nome.trim().split(/\s+/)
  return ((partes[0]?.[0] ?? '') + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

function Casca() {
  const { status, eu, conectado, pronta } = useSessao()
  const rota = useRota()
  const telas = telasDe(eu?.papeis ?? [])
  const atual = telas.find((t) => t.id === rota.tela)

  // Sem tela no endereço (ou tela que o papel não vê): vai para a primeira do menu.
  useEffect(() => {
    if (pronta && !atual && telas.length) navegar(telas[0].id)
  }, [pronta, atual, telas])

  const Componente = atual?.componente
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex h-[52px] shrink-0 items-center gap-7 bg-ibge px-6 text-white">
        <a href="#/" className="flex items-center gap-2.5 text-[17px] font-bold tracking-[.01em]">
          <Logo tamanho={24} escuro /> feixe
        </a>
        <nav className="flex h-full gap-1">
          {telas.map((t) => (
            <a
              key={t.id}
              href={`#/${t.id}`}
              aria-current={t.id === atual?.id ? 'page' : undefined}
              className={cn(
                'flex h-full items-center border-b-2 border-transparent px-3 text-white/70 hover:text-white',
                t.id === atual?.id && 'border-white text-white',
              )}
            >
              {t.rotulo}
            </a>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-3.5 text-xs text-white/80">
          <BotaoCamadas />
          {status && status.rotulo_ambiente && !/produ/i.test(status.ambiente) && (
            <span className="rounded px-2 py-0.5 font-semibold text-white" style={{ background: status.cor_ambiente }}>
              {status.rotulo_ambiente}
            </span>
          )}
          <span className="flex items-center gap-1.5" title={conectado ? 'O painel está falando com o QGIS' : 'O QGIS fechou'}>
            <span className={cn('size-2 rounded-full', conectado ? 'bg-[#4CC26F]' : 'bg-[#F0A040]')} />
            {conectado ? 'QGIS conectado' : 'QGIS desconectado'}
          </span>
          {eu && (
            <>
              <span>
                {eu.papel_rotulo}
                {eu.uf ? ` · ${eu.uf}` : ''}
              </span>
              <span
                className="grid size-[30px] place-items-center rounded-full bg-white/15 font-semibold text-white"
                title={`${eu.nome} (${eu.conta})`}
              >
                {iniciais(eu.nome)}
              </span>
            </>
          )}
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-[1120px] flex-1 flex-col gap-6 px-8 pt-7 pb-10">
        {!conectado && (
          <Card className="border-destructive">
            <CardContent className="text-sm">O QGIS fechou ou o plugin foi descarregado. Reabra o Feixe pelo QGIS.</CardContent>
          </Card>
        )}
        {atual && <h1 className="text-2xl font-semibold tracking-[-.01em]">{atual.rotulo}</h1>}
        {Componente && <Componente />}
      </main>
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
