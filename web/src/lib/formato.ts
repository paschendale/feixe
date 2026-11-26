// Formatos de número e data em pt-BR, no fuso de quem está olhando (o banco guarda UTC).
export const num = (n: number) => n.toLocaleString('pt-BR')

// Fuso de quem está olhando, mandado à API nas contas por dia (o servidor não sabe o fuso da estação).
export const FUSO = Intl.DateTimeFormat().resolvedOptions().timeZone || 'America/Sao_Paulo'

// "14:05"
export const hora = (iso: string | null) => (iso ? new Date(iso).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }) : '')

export function dataHora(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pt-BR', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
}

export const plural = (n: number, um: string, varios: string) => `${num(n)} ${n === 1 ? um : varios}`

// Nível da grade estatística: 5000 -> "5 km", 2500 -> "2,5 km", 200 -> "200 m".
export function nivelGrade(m: number | null) {
  if (m == null) return '—'
  return m >= 1000 ? `${(m / 1000).toLocaleString('pt-BR')} km` : `${m} m`
}

export const GERACAO: Record<string, string> = {
  grade: 'Grade estatística',
  amostra_area: 'Amostra por área',
  amostra_feicao: 'Amostra por feição',
  manual: 'Manual',
  nenhuma: 'Sem cargas',
}

const DIA_MS = 24 * 3600 * 1000

// Dias inteiros entre a data e hoje, no calendário de quem olha (0 = hoje).
export function diasAtras(iso: string | null): number | null {
  if (!iso) return null
  const d = new Date(iso)
  const hoje = new Date()
  const a = Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())
  const b = Date.UTC(hoje.getFullYear(), hoje.getMonth(), hoje.getDate())
  return Math.round((b - a) / DIA_MS)
}

// "17/11"
export function diaMes(iso: string | null) {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
}

// Última conclusão como se fala: "hoje", "ontem", "há 3 dias", "13/10 · há 35 dias", "ainda não".
export function quando(iso: string | null, longo = 7) {
  const n = diasAtras(iso)
  if (n === null) return 'ainda não'
  if (n <= 0) return 'hoje'
  if (n === 1) return 'ontem'
  return n > longo ? `${diaMes(iso)} · há ${n} dias` : `há ${n} dias`
}

// Sem conclusão há mais de uma semana: o supervisor precisa olhar (laranja nas tabelas).
export const parado = (iso: string | null) => (diasAtras(iso) ?? 0) > 7

export function saudacao() {
  const h = new Date().getHours()
  return h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite'
}

// "Terça-feira, 17 de novembro"
export function hojePorExtenso() {
  const s = new Date().toLocaleDateString('pt-BR', { weekday: 'long', day: 'numeric', month: 'long' })
  return s.charAt(0).toUpperCase() + s.slice(1)
}

export const primeiroNome = (nome: string | null | undefined) => (nome ?? '').trim().split(/\s+/)[0] ?? ''

// "a, b e c"
export function lista(xs: string[]) {
  if (xs.length <= 1) return xs.join('')
  return `${xs.slice(0, -1).join(', ')} e ${xs[xs.length - 1]}`
}

export const pc = (feitas: number, total: number) => (total ? Math.round((100 * feitas) / total) : 0)

// "folha" quando o lote é folha, "lote" quando é lote livre ou o tipo não é conhecido (D-156).
export const termoLote = (tipo: string | undefined | null, plural = false) => (tipo === 'folha' ? (plural ? 'folhas' : 'folha') : plural ? 'lotes' : 'lote')

// Com o artigo: "a folha" / "o lote".
export const oLote = (tipo: string | undefined | null) => (tipo === 'folha' ? 'a folha' : 'o lote')

// Todos são folha: a concordância do que vem depois vai para o feminino ("3 folhas marcadas", "2 lotes marcados").
export const soFolhas = (ls: { tipo?: string | null }[]) => ls.length > 0 && ls.every((l) => l.tipo === 'folha')

// "62 folhas e 3 lotes": a contagem separa folhas de lotes livres (D-156). Sem o tipo, conta como lote.
export function contarLotes(ls: { tipo?: string | null }[], depois = '') {
  const folhas = ls.filter((l) => l.tipo === 'folha').length
  const livres = ls.length - folhas
  const partes = [folhas && plural(folhas, 'folha', 'folhas'), livres && plural(livres, 'lote', 'lotes')].filter(Boolean)
  return `${partes.join(' e ') || '0 lotes'}${depois}`
}
