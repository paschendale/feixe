import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/lib/api'
import { useSessao } from '@/lib/sessao'

// Busca um recurso da API e recarrega quando chega um dos eventos SSE indicados (ex.: ['carga']).
// `caminho` nulo = não buscar ainda.
export function useApi<T>(caminho: string | null, eventos: string[] = []) {
  const [dados, setDados] = useState<T | null>(null)
  const [erro, setErro] = useState<string | null>(null)
  const [carregando, setCarregando] = useState(false)
  const { ultimo } = useSessao()
  const pedido = useRef(0)

  const recarregar = useCallback(async () => {
    if (!caminho) return
    const meu = ++pedido.current
    setCarregando(true)
    try {
      const r = await api<T>(caminho)
      if (meu === pedido.current) {
        setDados(r)
        setErro(null)
      }
    } catch (e) {
      if (meu === pedido.current) setErro((e as Error).message)
    } finally {
      if (meu === pedido.current) setCarregando(false)
    }
  }, [caminho])

  useEffect(() => {
    recarregar()
  }, [recarregar])

  useEffect(() => {
    if (ultimo && eventos.includes(ultimo.evento)) recarregar()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ultimo])

  return { dados, erro, carregando, recarregar }
}

// Chamada de ação (POST/PATCH/DELETE) com corpo JSON.
export function enviar<T = unknown>(caminho: string, corpo?: unknown, metodo = 'POST') {
  return api<T>(caminho, { method: metodo, body: corpo === undefined ? undefined : JSON.stringify(corpo) })
}
