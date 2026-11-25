import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { useEvento } from '@/lib/sse'

// Cache das leituras por caminho (D-104). Cada ida ao plugin custa idas e voltas até a CCAR, então:
// - pedidos iguais em andamento (várias telas, o mesmo evento SSE) viram uma chamada só;
// - ao abrir uma tela, ela mostra na hora o último resultado conhecido e atualiza por trás. Sempre atualiza: o que
//   outras pessoas mudam no banco não chega pelo SSE, que só traz o que este QGIS fez.
const ultimo = new Map<string, unknown>()
const emAndamento = new Map<string, Promise<unknown>>()

function buscar<T>(caminho: string): Promise<T> {
  let p = emAndamento.get(caminho) as Promise<T> | undefined
  if (!p) {
    p = api<T>(caminho)
      .then((r) => {
        ultimo.set(caminho, r)
        return r
      })
      .finally(() => emAndamento.delete(caminho))
    emAndamento.set(caminho, p)
  }
  return p
}

// Busca um recurso da API e recarrega quando chega um dos eventos SSE indicados (ex.: ['carga']). Eventos em rajada
// (o plugin publica fila, carga e lote juntos) viram uma recarga só; de `sincronizacao`, só conta o fim da rodada.
// `caminho` nulo = não buscar ainda. Com `manterAnterior`, trocar de caminho (um filtro) mantém os dados velhos na
// tela até os novos chegarem, em vez de esvaziar a lista (a tela usa `carregando` para esmaecer).
export function useApi<T>(caminho: string | null, eventos: string[] = [], { manterAnterior = false } = {}) {
  const [dados, setDados] = useState<T | null>(() => (caminho ? ((ultimo.get(caminho) as T) ?? null) : null))
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)
  const espera = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pedido = useRef(0)
  const caminhoAnterior = useRef(caminho)

  const recarregar = useCallback(async () => {
    if (!caminho) return
    const meu = ++pedido.current
    // Outro recurso (ex.: outra folha): não mostrar os dados do anterior enquanto o novo chega.
    if (ultimo.has(caminho)) setDados(ultimo.get(caminho) as T)
    else if (caminhoAnterior.current !== caminho && !manterAnterior) setDados(null)
    caminhoAnterior.current = caminho
    setCarregando(true)
    try {
      const r = await buscar<T>(caminho)
      if (meu === pedido.current) {
        setDados(r)
        setErro(null)
      }
    } catch (e) {
      if (meu === pedido.current) setErro((e as Error).message)
    } finally {
      if (meu === pedido.current) setCarregando(false)
    }
  }, [caminho, manterAnterior])

  useEffect(() => {
    recarregar()
  }, [recarregar])

  useEvento(eventos, (e) => {
    if (e.evento === 'sincronizacao' && e.dados.em_andamento) return
    clearTimeout(espera.current)
    espera.current = setTimeout(recarregar, 150)
  })
  useEffect(() => () => clearTimeout(espera.current), [])

  return { dados, erro, carregando, recarregar }
}

// Chamada de ação (POST/PATCH/DELETE) com corpo JSON.
export function enviar<T = unknown>(caminho: string, corpo?: unknown, metodo = 'POST') {
  return api<T>(caminho, { method: metodo, body: corpo === undefined ? undefined : JSON.stringify(corpo) })
}
