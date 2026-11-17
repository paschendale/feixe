import { useEffect, useState } from 'react'

// Rotas por hash (#/supervisao/folhas/12?grupo=a-1): o servidor local só serve index.html, e o hash sobrevive ao
// recarregar. `tela` é o módulo do topo; `partes` o resto do caminho (aba, id).
export type Rota = { tela: string; partes: string[]; query: URLSearchParams }

// Endereços de antes dos módulos (D-103), que o plugin ou um favorito ainda podem abrir.
const ANTIGAS: Record<string, string> = {
  'minhas-cargas': 'execucao',
  folhas: 'supervisao/folhas',
  equipe: 'supervisao/equipe',
  fluxos: 'supervisao/fluxos',
  atividades: 'catalogo/atividades',
}

function ler(): Rota {
  let bruto = window.location.hash.replace(/^#\/?/, '')
  const primeiro = bruto.split(/[/?]/)[0]
  if (ANTIGAS[primeiro]) bruto = ANTIGAS[primeiro] + bruto.slice(primeiro.length)
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

// Endereço com query: href('supervisao/folhas', { grupo: 'a-1' }) -> "#/supervisao/folhas?grupo=a-1".
export function href(caminho: string, query: Record<string, string | number | null | undefined> = {}) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) if (v !== null && v !== undefined && v !== '') q.set(k, String(v))
  const s = q.toString()
  return `#/${caminho.replace(/^\//, '')}${s ? `?${s}` : ''}`
}
