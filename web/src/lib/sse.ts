import { useEffect, useState } from 'react'
import { token } from './api'

export type Evento = { evento: string; dados: Record<string, unknown>; em: number }

// Escuta o stream de eventos do plugin. Quando o QGIS fecha, o stream cai e `conectado` vira false.
export function useEventos(nomes: string[], aoReceber?: (e: Evento) => void) {
  const [conectado, setConectado] = useState(false)
  const [ultimo, setUltimo] = useState<Evento | null>(null)
  useEffect(() => {
    const es = new EventSource(`/api/eventos?token=${encodeURIComponent(token())}`)
    es.addEventListener('conectado', () => setConectado(true))
    es.onerror = () => setConectado(false)
    const tratar = (ev: MessageEvent) => {
      const e = JSON.parse(ev.data) as Evento
      setUltimo(e)
      aoReceber?.(e)
    }
    for (const n of nomes) es.addEventListener(n, tratar as EventListener)
    es.addEventListener('encerrando', () => setConectado(false))
    return () => es.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nomes.join(',')])
  return { conectado, ultimo }
}
