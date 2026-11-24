import { useEffect, useState } from 'react'
import { CloudOff, Layers, RefreshCw } from 'lucide-react'
import { Logo } from '@/components/Logo'
import { AvisosProvider, useAvisar } from '@/lib/avisos'
import { plural } from '@/lib/formato'
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
      const r = await enviar<{ camadas: { nome: string; feicoes: number }[]; avisos?: string[] }>('/api/camadas/montar')
      avisar('Camadas no QGIS: ' + r.camadas.map((c) => `${c.nome} (${c.feicoes})`).join(', '))
      // Sem a CCAR, o grupo vem só com a Execução (C4): o porquê aparece também aqui.
      for (const a of r.avisos ?? []) avisar(a, 'erro')
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

// Sincronização do workspace com a CCAR (C3): sincronizado às hh:mm, sincronizando, offline com N pendentes. Clicar
// sincroniza agora (o mesmo "Sincronizar agora" da barra do QGIS).
function Sincronia() {
  const avisar = useAvisar()
  const { status, conectado, ultimo } = useSessao()
  const s = status?.sincronizacao
  // O que o push recusou ou perdeu num conflito (e o relógio errado) também aparece aqui, não só no QGIS.
  useEffect(() => {
    if (ultimo?.evento === 'sincronizacao') {
      for (const a of (ultimo.dados.avisos as string[] | undefined) ?? []) avisar(a, 'erro')
    }
    // A troca de online para offline e a volta (C4): o mesmo aviso da barra de mensagens do QGIS, uma vez só.
    if (ultimo?.evento === 'rede' && ultimo.dados.texto) {
      avisar(ultimo.dados.texto as string, ultimo.dados.online ? 'ok' : 'erro')
    }
  }, [ultimo, avisar])
  if (!conectado || !status?.credencial || !s) return null
  const pendentes = s.pendentes ?? 0
  const aEnviar = pendentes ? plural(pendentes, 'alteração a enviar', 'alterações a enviar') : null
  const hora = s.ultima_sincronizacao
    ? new Date(s.ultima_sincronizacao).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' })
    : null
  const offline = s.online === false || s.ultimo_estado === 'offline'
  let texto: string
  let Icone = RefreshCw
  if (s.em_andamento) texto = 'Sincronizando…'
  else if (offline) {
    texto = aEnviar ? `Offline · ${aEnviar}` : 'Offline'
    Icone = CloudOff
  } else if (s.ultimo_estado === 'erro') texto = 'Sincronização falhou'
  else if (aEnviar) texto = aEnviar
  else texto = hora ? `Sincronizado às ${hora}` : 'Ainda não sincronizado'
  const dica = [
    hora ? `Última sincronização às ${hora}.` : 'Ainda não sincronizou.',
    offline ? 'Sem a CCAR: o Feixe segue offline. O que você fizer em Minhas cargas fica guardado e vai para a CCAR quando a conexão voltar.' : null,
    s.ultimo_estado === 'erro' && s.mensagem ? `Última tentativa: ${s.mensagem}` : null,
    'Clique para sincronizar agora.',
  ]
    .filter(Boolean)
    .join(' ')
  async function agora() {
    try {
      await enviar('/api/sincronizar')
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }
  return (
    <button onClick={agora} disabled={s.em_andamento} title={dica} aria-live="polite" className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-white/85 hover:bg-white/12 hover:text-white disabled:opacity-80">
      <Icone className={cn('size-3.5', s.em_andamento && 'animate-spin')} aria-hidden />
      {texto}
    </button>
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
          <Sincronia />
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
