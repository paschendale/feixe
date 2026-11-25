import { useEffect, useRef, useState } from 'react'
import { token } from './api'

export type Evento = { evento: string; dados: Record<string, unknown>; em: number }
type Ouvinte = (e: Evento) => void

// Cada interessado assina os eventos que quer. Um estado único com "o último evento" perdia eventos: o plugin
// publica vários de uma vez (fila, carga, lote) e o React juntava as mudanças num render só.
const ouvintes = new Set<Ouvinte>()

function assinar(fn: Ouvinte) {
  ouvintes.add(fn)
  return () => {
    ouvintes.delete(fn)
  }
}

// Chama `fn` a cada evento de um dos `nomes`. `fn` pode mudar a cada render sem refazer a assinatura.
export function useEvento(nomes: string[], fn: Ouvinte) {
  const ref = useRef(fn)
  ref.current = fn
  const chave = nomes.join(',')
  useEffect(() => {
    if (!chave) return
    const lista = chave.split(',')
    return assinar((e) => {
      if (lista.includes(e.evento)) ref.current(e)
    })
  }, [chave])
}

// Escuta o stream de eventos do plugin (uma conexão só, na sessão). Quando o QGIS fecha, o stream cai e
// `conectado` vira false.
export function useEventos(nomes: string[]) {
  const [conectado, setConectado] = useState(false)
  useEffect(() => {
    const es = new EventSource(`/api/eventos?token=${encodeURIComponent(token())}`)
    es.addEventListener('conectado', () => setConectado(true))
    es.onerror = () => setConectado(false)
    const tratar = (ev: MessageEvent) => {
      const e = JSON.parse(ev.data) as Evento
      for (const fn of [...ouvintes]) fn(e)
    }
    for (const n of nomes) es.addEventListener(n, tratar as EventListener)
    es.addEventListener('encerrando', () => setConectado(false))
    return () => es.close()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nomes.join(',')])
  return { conectado }
}
