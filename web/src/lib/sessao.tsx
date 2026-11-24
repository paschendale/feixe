import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, type EstadoSincronizacao, type Eu, type Papel, type Status } from '@/lib/api'
import { useEventos, type Evento } from '@/lib/sse'

type Sessao = {
  status: Status | null
  eu: Eu | null
  conectado: boolean
  // Já se tentou carregar o usuário (com ou sem sucesso): antes disso o menu ainda não sabe o papel.
  pronta: boolean
  tem: (...papeis: Papel[]) => boolean
  // Último evento SSE recebido: as telas recarregam os dados quando chega um evento que lhes interessa.
  ultimo: Evento | null
  recarregar: () => void
}

const Ctx = createContext<Sessao | null>(null)

// Eventos que o plugin publica. Cada item da fase B acrescenta os seus aqui.
export const EVENTOS = ['estado', 'configuracao', 'carga', 'lote', 'fluxo', 'atividade', 'fila', 'qgis', 'sincronizacao', 'rede']

export function SessaoProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [eu, setEu] = useState<Eu | null>(null)
  const [pronta, setPronta] = useState(false)
  const recarregar = useCallback(() => {
    api<Status>('/api/status').then(setStatus).catch(() => setStatus(null))
    // Sem banco ou sem credencial, fica sem usuário; não é erro da tela.
    api<Eu>('/api/eu')
      .then(setEu)
      .catch(() => setEu(null))
      .finally(() => setPronta(true))
  }, [])
  const { conectado, ultimo } = useEventos(EVENTOS, (e) => {
    if (e.evento === 'estado' || e.evento === 'configuracao') recarregar()
    // A sincronização em segundo plano (C3) avisa quando começa e quando termina: o indicador muda sem recarregar.
    if (e.evento === 'sincronizacao') {
      const sinc = e.dados as unknown as EstadoSincronizacao
      setStatus((s) => (s ? { ...s, sincronizacao: sinc, online: sinc.online ?? s.online } : s))
    }
  })
  useEffect(() => recarregar(), [recarregar])
  const tem = useCallback((...p: Papel[]) => !!eu && p.some((x) => eu.papeis.includes(x)), [eu])
  return <Ctx.Provider value={{ status, eu, conectado, pronta, tem, ultimo, recarregar }}>{children}</Ctx.Provider>
}

export function useSessao(): Sessao {
  const s = useContext(Ctx)
  if (!s) throw new Error('useSessao fora do SessaoProvider')
  return s
}
