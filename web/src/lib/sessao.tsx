import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, type Eu, type Papel, type Status } from '@/lib/api'
import { useEventos, type Evento } from '@/lib/sse'

type Sessao = {
  status: Status | null
  eu: Eu | null
  conectado: boolean
  tem: (...papeis: Papel[]) => boolean
  // Último evento SSE recebido: as telas recarregam os dados quando chega um evento que lhes interessa.
  ultimo: Evento | null
  recarregar: () => void
}

const Ctx = createContext<Sessao | null>(null)

// Eventos que o plugin publica. Cada item da fase B acrescenta os seus aqui.
export const EVENTOS = ['estado', 'configuracao', 'carga', 'lote', 'fluxo', 'atividade', 'fila', 'qgis']

export function SessaoProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [eu, setEu] = useState<Eu | null>(null)
  const recarregar = useCallback(() => {
    api<Status>('/api/status').then(setStatus).catch(() => setStatus(null))
    // Sem banco ou sem credencial, fica sem usuário; não é erro da tela.
    api<Eu>('/api/eu').then(setEu).catch(() => setEu(null))
  }, [])
  const { conectado, ultimo } = useEventos(EVENTOS, (e) => {
    if (e.evento === 'estado' || e.evento === 'configuracao') recarregar()
  })
  useEffect(() => recarregar(), [recarregar])
  const tem = useCallback((...p: Papel[]) => !!eu && p.some((x) => eu.papeis.includes(x)), [eu])
  return <Ctx.Provider value={{ status, eu, conectado, tem, ultimo, recarregar }}>{children}</Ctx.Provider>
}

export function useSessao(): Sessao {
  const s = useContext(Ctx)
  if (!s) throw new Error('useSessao fora do SessaoProvider')
  return s
}
