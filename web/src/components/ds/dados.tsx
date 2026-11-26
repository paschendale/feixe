import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { COR, TOM, type Tom } from './cores'

// Visualização de andamento: barra empilhada, anel, legenda, números grandes e mini-barras por dia.

export type Parte = { valor: number; cor: string; rotulo?: string }

// Barra empilhada sobre o total, num trilho cinza translúcido.
export function Barra({ partes, total, altura = 6, className }: { partes: Parte[]; total: number; altura?: number; className?: string }) {
  return (
    <div className={cn('flex overflow-hidden rounded-full', className)} style={{ height: altura, background: COR.vazio }}>
      {total > 0 &&
        partes.map((p, i) =>
          p.valor > 0 ? <div key={i} style={{ width: `${(100 * p.valor) / total}%`, background: p.cor }} title={p.rotulo ? `${p.rotulo}: ${p.valor}` : undefined} /> : null,
        )}
    </div>
  )
}

// Anel de andamento (como os anéis do Atividade): partes empilhadas em volta, o resto no trilho. `centro` vai no meio.
export function Anel({ partes, total, tamanho = 32, espessura = 3.5, centro, rotulo }: { partes: Parte[]; total: number; tamanho?: number; espessura?: number; centro?: ReactNode; rotulo?: string }) {
  const r = (tamanho - espessura) / 2
  const c = 2 * Math.PI * r
  let acumulado = 0
  return (
    <span className="relative inline-grid shrink-0 place-items-center" style={{ width: tamanho, height: tamanho }} role={rotulo ? 'img' : undefined} aria-label={rotulo}>
      <svg width={tamanho} height={tamanho} viewBox={`0 0 ${tamanho} ${tamanho}`} className="-rotate-90" aria-hidden>
        <circle cx={tamanho / 2} cy={tamanho / 2} r={r} fill="none" stroke={COR.vazio} strokeWidth={espessura} />
        {total > 0 &&
          partes.map((p, i) => {
            if (p.valor <= 0) return null
            const frac = Math.min(1, p.valor / total)
            const el = (
              <circle
                key={i}
                cx={tamanho / 2}
                cy={tamanho / 2}
                r={r}
                fill="none"
                stroke={p.cor}
                strokeWidth={espessura}
                strokeLinecap={frac < 1 ? 'round' : 'butt'}
                strokeDasharray={`${Math.max(frac * c - (frac < 1 ? espessura * 0.6 : 0), 0.01)} ${c}`}
                strokeDashoffset={-acumulado * c}
              />
            )
            acumulado += frac
            return el
          })}
      </svg>
      {centro !== undefined && <span className="tab absolute text-legenda font-semibold">{centro}</span>}
    </span>
  )
}

export function Legenda({ itens }: { itens: { cor: string; rotulo: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-3.5 gap-y-1 text-rodape text-muted-foreground">
      {itens.map((i) => (
        <span key={i.rotulo} className="inline-flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-full" style={{ background: i.cor }} />
          {i.rotulo}
        </span>
      ))}
    </div>
  )
}

// Número grande (um contador que pede atenção ou resume a tela).
export function Numero({ valor, alerta, className }: { valor: number; alerta?: boolean; className?: string }) {
  return <span className={cn('tab text-numero font-bold', alerta ? 'text-alerta' : 'text-primary', className)}>{valor.toLocaleString('pt-BR')}</span>
}

// Métrica: número grande, o que ele conta e um detalhe (ou um gráfico pequeno) embaixo. Com `href`, a métrica leva
// ao lugar onde se age sobre ela.
export function Metrica({ valor, rotulo, detalhe, tom, href, className, children }: { valor: ReactNode; rotulo: ReactNode; detalhe?: ReactNode; tom?: Tom; href?: string; className?: string; children?: ReactNode }) {
  const corpo = (
    <>
      <span className={cn('tab text-numero font-bold', tom ? TOM[tom].texto : 'text-foreground')}>{typeof valor === 'number' ? valor.toLocaleString('pt-BR') : valor}</span>
      <span className="font-medium">{rotulo}</span>
      {detalhe && <span className="text-nota text-muted-foreground">{detalhe}</span>}
      {children}
    </>
  )
  const cls = cn('flex min-w-0 flex-col gap-0.5 rounded-xl bg-card px-5 py-4 shadow-cartao', href && 'transition-shadow hover:shadow-flutuante', className)
  return href ? (
    <a href={href} className={cls}>
      {corpo}
    </a>
  ) : (
    <div className={cls}>{corpo}</div>
  )
}

// Mini-barras por dia (conclusões, avaliações): a última barra (hoje) no azul, as outras no azul-aço.
export function BarrasDia({ dias, altura = 40, className }: { dias: { dia: string; rotulo: string; n: number }[]; altura?: number; className?: string }) {
  const max = Math.max(1, ...dias.map((d) => d.n))
  const descricao = dias.map((d) => `${d.rotulo}: ${d.n}`).join(', ')
  return (
    <div role="img" aria-label={`Por dia, ${descricao}`} className={cn('flex items-end gap-[3px]', className)} style={{ height: altura }}>
      {dias.map((d, i) => (
        <div
          key={d.dia}
          title={`${d.rotulo}: ${d.n}`}
          className="flex-1 rounded-xs"
          style={{ height: d.n ? `${Math.max(8, (100 * d.n) / max)}%` : 2, background: d.n ? (i === dias.length - 1 ? COR.concluida : COR.comAlguem) : COR.vazio }}
        />
      ))}
    </div>
  )
}
