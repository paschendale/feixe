import type { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'

// Controles próprios do Feixe (os do shadcn ficam em components/ui): controle segmentado, fichas de filtro, link com
// seta, campo rotulado e os rótulos que não mudam de largura.

// Controle segmentado: escolhas exclusivas e poucas (2 a 6), como o filtro de uma lista.
export function Segmentado<T extends string>({ opcoes, ativa, escolher, rotulo, className }: { opcoes: { id: T; rotulo: ReactNode; contagem?: ReactNode }[]; ativa: T; escolher: (id: T) => void; rotulo: string; className?: string }) {
  return (
    <div role="radiogroup" aria-label={rotulo} className={cn('inline-flex w-fit max-w-full flex-wrap gap-0.5 rounded-lg bg-preenchimento p-[3px]', className)}>
      {opcoes.map((o) => {
        const on = o.id === ativa
        return (
          <button
            key={o.id}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => escolher(o.id)}
            className={cn('inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-nota transition-colors', on ? 'bg-card font-medium text-foreground shadow-controle' : 'text-texto-2 hover:text-foreground')}
          >
            <RotuloNegrito ativo={on} peso="font-medium">
              {o.rotulo}
            </RotuloNegrito>
            {o.contagem !== undefined && <span className="tab text-muted-foreground">{o.contagem}</span>}
          </button>
        )
      })}
    </div>
  )
}

// Fichas (uma por atividade em produção), como os subgrupos do QGIS: muitas escolhas, com contagem. A última,
// tracejada, é "todas".
export type Ficha = { id: string; rotulo: ReactNode; contagem?: ReactNode; todas?: boolean }

export function Fichas({ fichas, ativa, escolher, rotulo }: { fichas: Ficha[]; ativa: string; escolher: (id: string) => void; rotulo: string }) {
  return (
    <div role="group" aria-label={rotulo} className="flex flex-wrap gap-2">
      {fichas.map((f) => {
        const on = f.id === ativa
        return (
          <button
            key={f.id}
            type="button"
            aria-pressed={on}
            onClick={() => escolher(f.id)}
            className={cn(
              'inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-nota transition-colors',
              on ? 'bg-primary text-primary-foreground' : f.todas ? 'border border-dashed border-input text-texto-2 hover:bg-preenchimento-2' : 'bg-card text-foreground shadow-controle hover:bg-preenchimento-2',
            )}
          >
            {f.rotulo}
            {f.contagem !== undefined && <span className={cn('tab font-semibold', on ? 'text-primary-foreground/80' : 'text-muted-foreground')}>{f.contagem}</span>}
          </button>
        )
      })}
    </div>
  )
}

// Link de navegação com a seta (chevron) do sistema.
export function LinkSeta({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} className={cn('inline-flex w-fit items-center gap-0.5 font-medium text-primary hover:underline', className)}>
      {children}
      <ChevronRight className="size-[1.1em]" aria-hidden />
    </a>
  )
}

// Campo de filtro ou formulário: rótulo pequeno em cima e o controle embaixo. `lado` = rótulo à esquerda (linhas de
// formulário compactas). `grupo` = o rótulo vale para vários controles (vira um grupo, não um <label>).
export function Campo({ rotulo, children, className, dica, lado, grupo }: { rotulo: ReactNode; children: ReactNode; className?: string; dica?: ReactNode; lado?: boolean; grupo?: boolean }) {
  const cls = cn(lado ? 'flex items-center gap-2.5' : 'flex flex-col gap-1.5', 'text-rodape font-medium text-muted-foreground', className)
  const dicaEl = dica && <span className="font-normal">{dica}</span>
  if (grupo)
    return (
      <div role="group" className={cls}>
        <span>{rotulo}</span>
        <div className="text-corpo font-normal text-foreground">{children}</div>
        {dicaEl}
      </div>
    )
  return (
    <label className={cls}>
      {rotulo}
      {children}
      {dicaEl}
    </label>
  )
}

// Rótulo que troca de texto (ex.: "Distribuir" → "Distribuindo…") sem mudar de largura: os dois ocupam a mesma
// célula do grid e o botão fica com a largura do maior.
export function RotuloEstavel({ ocupado, rotulo, rotuloOcupado }: { ocupado: boolean; rotulo: ReactNode; rotuloOcupado: ReactNode }) {
  return (
    <span className="inline-grid">
      <span className={cn('col-start-1 row-start-1', ocupado && 'invisible')}>{rotulo}</span>
      <span aria-hidden={!ocupado} className={cn('col-start-1 row-start-1', !ocupado && 'invisible')}>
        {rotuloOcupado}
      </span>
    </span>
  )
}

// Texto que fica em negrito quando ativo sem empurrar os vizinhos: a versão em negrito, invisível, reserva a largura.
export function RotuloNegrito({ children, ativo, peso = 'font-semibold' }: { children: ReactNode; ativo: boolean; peso?: string }) {
  return (
    <span className="inline-grid">
      <span aria-hidden className={cn('invisible col-start-1 row-start-1', peso)}>
        {children}
      </span>
      <span className={cn('col-start-1 row-start-1', ativo && peso)}>{children}</span>
    </span>
  )
}
