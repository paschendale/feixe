import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

// Peças comuns das telas do painel (D-103), no desenho do canvas: blocos brancos, seções com link para o módulo,
// barras de andamento e fichas de atividade.

export const COR = {
  concluida: '#004182',
  comAlguem: '#9DB4D8',
  vazio: '#E3E8EF',
  alerta: '#8A5A00',
  alertaFundo: '#FCEBD2',
}

export function Bloco({ className, children, ...props }: React.ComponentProps<'div'>) {
  return (
    <div className={cn('flex flex-col gap-3 rounded-[10px] border bg-card p-5', className)} {...props}>
      {children}
    </div>
  )
}

export function Conteudo({ largura = 1240, className, children }: { largura?: number; className?: string; children: ReactNode }) {
  return (
    <main className={cn('mx-auto flex w-full flex-col gap-5 px-6 pt-6 pb-16', className)} style={{ maxWidth: largura }}>
      {children}
    </main>
  )
}

export type Aba = { id: string; rotulo: ReactNode; href?: string; contagem?: number; desabilitada?: boolean }

// Faixa branca com o título do módulo e as abas.
export function CabecalhoModulo({ titulo, sub, abas, ativa }: { titulo: string; sub?: string; abas: Aba[]; ativa: string }) {
  return (
    <div className="border-b bg-card">
      <div className="mx-auto flex max-w-[1240px] flex-col gap-3.5 px-6 pt-5">
        <div className="flex flex-wrap items-baseline gap-x-3.5">
          <h1 className="text-2xl font-semibold">{titulo}</h1>
          {sub && <span className="text-sm text-muted-foreground">{sub}</span>}
        </div>
        <nav aria-label={titulo} className="flex flex-wrap gap-1">
          {abas.map((a) =>
            a.desabilitada || !a.href ? (
              <span key={a.id} className="border-b-2 border-transparent px-3.5 py-2.5 text-muted-foreground/70">
                {a.rotulo}
              </span>
            ) : (
              <a
                key={a.id}
                href={a.href}
                aria-current={a.id === ativa ? 'page' : undefined}
                className={cn(
                  'inline-flex items-center gap-2 border-b-2 px-3.5 py-2.5',
                  a.id === ativa ? 'border-ibge font-semibold text-ibge' : 'border-transparent text-[#3D4B5C] hover:text-ibge',
                )}
              >
                {a.rotulo}
                {!!a.contagem && (
                  <span className="rounded-full px-2 text-xs font-semibold" style={{ background: COR.alertaFundo, color: COR.alerta }}>
                    {a.contagem.toLocaleString('pt-BR')}
                  </span>
                )}
              </a>
            ),
          )}
        </nav>
      </div>
    </div>
  )
}

// Título de seção do Início: nome, explicação e o link para o módulo.
export function Secao({ titulo, sub, link, children }: { titulo: string; sub?: string; link?: { href: string; rotulo: string }; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1.5 border-b border-[#DCE2EA] pb-3">
        <h2 className="text-xl font-semibold">{titulo}</h2>
        {sub && <span className="text-muted-foreground">{sub}</span>}
        {link && (
          <a href={link.href} className="ml-auto font-semibold text-ibge hover:underline">
            {link.rotulo} →
          </a>
        )}
      </div>
      {children}
    </section>
  )
}

export function Rotulo({ children }: { children: ReactNode }) {
  return <h3 className="text-[13px] font-semibold tracking-[.04em] text-muted-foreground uppercase">{children}</h3>
}

export function LinkSeta({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} className={cn('font-semibold text-ibge hover:underline', className)}>
      {children} →
    </a>
  )
}

export type Parte = { valor: number; cor: string; rotulo?: string }

// Barra empilhada sobre o total (o resto fica no cinza do fundo).
export function Barra({ partes, total, altura = 8, className }: { partes: Parte[]; total: number; altura?: number; className?: string }) {
  return (
    <div className={cn('flex overflow-hidden rounded', className)} style={{ height: altura, background: COR.vazio }}>
      {total > 0 &&
        partes.map((p, i) =>
          p.valor > 0 ? <div key={i} style={{ width: `${(100 * p.valor) / total}%`, background: p.cor }} title={p.rotulo ? `${p.rotulo}: ${p.valor}` : undefined} /> : null,
        )}
    </div>
  )
}

export function Legenda({ itens }: { itens: { cor: string; rotulo: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-3.5 gap-y-1 text-xs text-muted-foreground">
      {itens.map((i) => (
        <span key={i.rotulo} className="inline-flex items-center gap-1.5">
          <span className="inline-block size-[9px] rounded-[2px]" style={{ background: i.cor }} />
          {i.rotulo}
        </span>
      ))}
    </div>
  )
}

// Fichas (uma por atividade em produção), como os subgrupos do QGIS; a última, tracejada, é "todas".
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
              'inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5',
              on ? 'border-ibge bg-ibge text-white' : f.todas ? 'border-dashed border-input text-[#3D4B5C] hover:bg-accent' : 'border-input bg-card hover:bg-accent',
            )}
          >
            {f.rotulo}
            {f.contagem !== undefined && <b className="tab">{f.contagem}</b>}
          </button>
        )
      })}
    </div>
  )
}

// Número grande de um cartão "Precisa de você".
export function Numero({ valor, alerta }: { valor: number; alerta?: boolean }) {
  return (
    <span className="tab text-[34px] leading-tight font-bold" style={{ color: alerta ? COR.alerta : COR.concluida }}>
      {valor.toLocaleString('pt-BR')}
    </span>
  )
}

export function Carregando({ erro }: { erro?: string | null }) {
  return erro ? <p className="text-sm text-destructive">{erro}</p> : <p className="text-sm text-muted-foreground">Carregando…</p>
}
