// Cliente da API local do plugin. O token chega na URL de abertura (?token=...) e fica na sessionStorage.
const CHAVE = 'feixe.token'

export function token(): string {
  const url = new URL(window.location.href)
  const daUrl = url.searchParams.get('token')
  if (daUrl) {
    sessionStorage.setItem(CHAVE, daUrl)
    url.searchParams.delete('token')
    window.history.replaceState({}, '', url.pathname + url.search + url.hash)
  }
  return sessionStorage.getItem(CHAVE) ?? ''
}

export class ErroApi extends Error {
  status: number
  constructor(status: number, mensagem: string) {
    super(mensagem)
    this.status = status
  }
}

export async function api<T = unknown>(caminho: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(caminho, {
    ...init,
    headers: { 'Content-Type': 'application/json', 'X-Feixe-Token': token(), ...(init.headers ?? {}) },
  })
  const corpo = await r.json().catch(() => ({}))
  if (!r.ok) throw new ErroApi(r.status, (corpo as { erro?: string }).erro ?? r.statusText)
  return corpo as T
}

export type Status = {
  ambiente: string
  rotulo_ambiente: string
  cor_ambiente: string
  banco: string
  credencial: boolean
  versao_plugin: string
  qgis: string
  clientes_sse: number
  online: boolean
  usuario: string | null
  detalhe: string
}

export type Folha = {
  id: number
  cd_mi: string
  nm_carta: string | null
  nomenclatura: string
  xmin: number
  ymin: number
  xmax: number
  ymax: number
}
