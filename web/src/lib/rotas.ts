import { useEffect, useState } from 'react'

// Rotas por hash (#/minhas-cargas, #/folhas/12): o servidor local só serve index.html, e o hash sobrevive ao recarregar.
export type Rota = { tela: string; partes: string[]; query: URLSearchParams }

function ler(): Rota {
  const bruto = window.location.hash.replace(/^#\/?/, '')
  const [caminho, q = ''] = bruto.split('?')
  const partes = caminho.split('/').filter(Boolean)
  return { tela: partes[0] ?? '', partes: partes.slice(1), query: new URLSearchParams(q) }
}

export function useRota(): Rota {
  const [rota, setRota] = useState(ler)
  useEffect(() => {
    const ao = () => setRota(ler())
    window.addEventListener('hashchange', ao)
    return () => window.removeEventListener('hashchange', ao)
  }, [])
  return rota
}

export function navegar(caminho: string) {
  window.location.hash = '/' + caminho.replace(/^\//, '')
}
