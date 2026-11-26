// Cores de dados e de estado como referências aos tokens de index.css: servem em `style` e nos atributos de SVG
// (fill/stroke). Nunca hex nas telas; se faltar uma cor, ela nasce como token.
export const COR = {
  concluida: 'var(--dado-concluida)',
  comAlguem: 'var(--dado-com-alguem)',
  naFila: 'var(--dado-na-fila)',
  vazio: 'var(--preenchimento)',
  alerta: 'var(--alerta)',
  alertaFundo: 'var(--alerta-suave)',
  sucesso: 'var(--sucesso)',
  perigo: 'var(--destructive)',
  // Amostra não conforme (CQ): laranja, legível sobre o branco e distinto do azul das conformes.
  naoConforme: 'var(--dado-nao-conforme)',
  textoClaro: 'var(--dado-texto-claro)',
}

// Tons de estado: texto + fundo suave do mesmo par. Usados por Selo, Nota, Metrica e pelos números de alerta.
export type Tom = 'neutro' | 'info' | 'sucesso' | 'alerta' | 'perigo'

export const TOM: Record<Tom, { texto: string; fundo: string }> = {
  neutro: { texto: 'text-texto-2', fundo: 'bg-preenchimento-2' },
  info: { texto: 'text-info', fundo: 'bg-info-suave' },
  sucesso: { texto: 'text-sucesso', fundo: 'bg-sucesso-suave' },
  alerta: { texto: 'text-alerta', fundo: 'bg-alerta-suave' },
  perigo: { texto: 'text-perigo', fundo: 'bg-perigo-suave' },
}
