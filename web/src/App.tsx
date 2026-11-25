import { useEffect, useState } from 'react'
import { Layers } from 'lucide-react'
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
      className="flex items-center gap-1.5 rounded-md bg-white/12 px-3 py-[7px] text-white hover:bg-white/20 disabled:opacity-40"
    >
      <Layers className="size-3.5" /> {ocupado ? 'Montando…' : 'Camadas no QGIS'}
    </button>
  )
}

// Primeiro e último nome: "Victor dos Santos Marotta" -> "VM".
function iniciais(nome: string) {
  const partes = nome.trim().split(/\s+/)
  return ((partes[0]?.[0] ?? '') + (partes.length > 1 ? partes[partes.length - 1][0] : '')).toUpperCase()
}

// Bolinha e texto da conexão: verde com o QGIS e a CCAR, laranja sem a CCAR, cinza com o QGIS fechado. Fora da
// produção, o ambiente vem junto (era um selo à parte).
function Conexao() {
  const { status, conectado } = useSessao()
  const online = conectado && !!status?.online
  const texto = !conectado ? 'QGIS fechado' : online ? 'Conectado' : 'Sem a CCAR'
  const ambiente = status?.rotulo_ambiente && !/produ/i.test(status.ambiente) ? status.rotulo_ambiente : null
  return (
    <span className="flex items-center gap-1.5" title={status?.detalhe || (conectado ? 'O painel está falando com o QGIS' : 'Reabra o Feixe pelo QGIS')}>
      <span className={cn('size-2 rounded-full', online ? 'bg-[#4CC26F]' : conectado ? 'bg-[#F0A040]' : 'bg-white/40')} />
      {texto}
      {ambiente ? ` · ${ambiente}` : ''}
    </span>
  )
}

function Casca() {
  const { eu, conectado, pronta } = useSessao()
  const rota = useRota()
  const telas = telasDe(eu?.papeis ?? [])
  const atual = telas.find((t) => t.id === rota.tela)

  // Sem módulo no endereço (ou um que o papel não vê): vai para o Início.
  useEffect(() => {
    if (pronta && !atual && telas.length) navegar(telas[0].id)
  }, [pronta, atual, telas])

  const Componente = atual?.componente
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex min-h-[52px] shrink-0 flex-wrap items-center gap-x-7 gap-y-2 bg-ibge px-6 py-2 text-white">
        <a href="#/inicio" className="flex items-center gap-2.5 text-[17px] font-bold tracking-[.01em]">
          <Logo tamanho={24} escuro /> feixe
        </a>
        <nav aria-label="Módulos" className="flex flex-wrap gap-1">
          {telas
            .filter((t) => !t.oculta)
            .map((t) => (
              <a
                key={t.id}
                href={`#/${t.id}`}
                aria-current={t.id === atual?.id ? 'page' : undefined}
                className={cn(
                  'border-b-2 border-transparent px-3 py-2 text-white/78 hover:text-white',
                  t.id === atual?.id && 'border-white font-semibold text-white',
                )}
              >
                {t.rotulo}
              </a>
            ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-3.5 text-[13px] text-white/85">
          <Conexao />
          <BotaoCamadas />
          <a
            href="#/sobre"
            className="grid size-8 place-items-center rounded-full bg-white/18 font-semibold text-white hover:bg-white/28"
            title={eu ? `${eu.nome} (${eu.conta}) · ${eu.papel_rotulo}${eu.uf ? ` · ${eu.uf}` : ''}: conta e sobre` : 'Conta e sobre'}
            aria-label={eu ? `${eu.nome}: conta e sobre` : 'Conta e sobre'}
          >
            {eu ? iniciais(eu.nome) : '?'}
          </a>
        </div>
      </header>
      {!conectado && (
        <div className="border-b border-destructive/30 bg-destructive/10 px-6 py-2.5 text-center text-sm">
          O QGIS fechou ou o plugin foi descarregado. Reabra o Feixe pelo QGIS.
        </div>
      )}
      {Componente && <Componente />}
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
