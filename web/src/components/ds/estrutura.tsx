import type { ReactNode } from 'react'
import { ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { RotuloNegrito } from './controles'

// Estrutura das telas: a coluna de conteúdo, o cabeçalho do módulo, as seções do Início, as superfícies (Bloco) e as
// listas agrupadas.

export function Conteudo({ largura = 1240, className, children }: { largura?: number; className?: string; children: ReactNode }) {
  return (
    <main className={cn('mx-auto flex w-full flex-col gap-6 px-6 pt-7 pb-20', className)} style={{ maxWidth: largura }}>
      {children}
    </main>
  )
}

// Superfície branca: a unidade visual das telas. Sem borda; a sombra fina separa do fundo. `poco` = superfície
// cinza embutida dentro de outra (um grupo dentro de um diálogo ou da gaveta).
export function Bloco({ className, children, poco, ...props }: React.ComponentProps<'div'> & { poco?: boolean }) {
  return (
    <div className={cn('flex flex-col gap-3 rounded-xl', poco ? 'bg-preenchimento-2 p-4' : 'bg-card p-5 shadow-cartao', className)} {...props}>
      {children}
    </div>
  )
}

// Título de um Bloco: nome, explicação curta e uma ação à direita (link ou botão).
export function TituloBloco({ titulo, sub, acao, className }: { titulo: ReactNode; sub?: ReactNode; acao?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5', className)}>
      <h3 className="text-titulo-3 font-semibold">{titulo}</h3>
      {sub && <span className="text-nota text-muted-foreground">{sub}</span>}
      {acao && <div className="ml-auto">{acao}</div>}
    </div>
  )
}

export type Aba = { id: string; rotulo: ReactNode; href?: string; contagem?: number; desabilitada?: boolean }

// Cabeçalho do módulo: título grande e as abas num controle segmentado. Fica no fundo da página (sem faixa branca).
export function CabecalhoModulo({ titulo, sub, abas, ativa }: { titulo: string; sub?: string; abas: Aba[]; ativa: string }) {
  return (
    <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-4 px-6 pt-7">
      <div className="flex flex-wrap items-baseline gap-x-3.5">
        <h1 className="text-titulo-grande font-bold">{titulo}</h1>
        {sub && <span className="text-muted-foreground">{sub}</span>}
      </div>
      <nav aria-label={titulo} className="flex w-fit max-w-full flex-wrap gap-0.5 rounded-lg bg-preenchimento p-[3px]">
        {abas.map((a) =>
          a.desabilitada || !a.href ? (
            <span key={a.id} className="rounded-md px-3.5 py-1.5 text-terciario">
              {a.rotulo}
            </span>
          ) : (
            <a
              key={a.id}
              href={a.href}
              aria-current={a.id === ativa ? 'page' : undefined}
              className={cn(
                'inline-flex items-center gap-2 rounded-md px-3.5 py-1.5 transition-colors',
                a.id === ativa ? 'bg-card text-foreground shadow-controle' : 'text-texto-2 hover:bg-card/60 hover:text-foreground',
              )}
            >
              <RotuloNegrito ativo={a.id === ativa}>{a.rotulo}</RotuloNegrito>
              {!!a.contagem && <span className="tab rounded-full bg-alerta-suave px-1.5 text-rodape font-semibold text-alerta">{a.contagem.toLocaleString('pt-BR')}</span>}
            </a>
          ),
        )}
      </nav>
    </div>
  )
}

// Seção do Início: título, explicação e o link para o módulo.
export function Secao({ titulo, sub, link, children }: { titulo: string; sub?: string; link?: { href: string; rotulo: string }; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="text-titulo-1 font-bold">{titulo}</h2>
        {sub && <span className="text-muted-foreground">{sub}</span>}
        {link && (
          <a href={link.href} className="ml-auto inline-flex items-center gap-0.5 font-medium text-primary hover:underline">
            {link.rotulo}
            <ChevronRight className="size-4" aria-hidden />
          </a>
        )}
      </div>
      {children}
    </section>
  )
}

// Rótulo de grupo (acima de uma lista ou de um conjunto de cartões), como os cabeçalhos das listas agrupadas.
export function Rotulo({ children, className }: { children: ReactNode; className?: string }) {
  return <h3 className={cn('px-1 text-rodape font-semibold tracking-[.04em] text-muted-foreground uppercase', className)}>{children}</h3>
}

// Lista agrupada: linhas numa superfície só, separadas por um fio que começa depois do ícone.
export function Lista({ className, children, ...props }: React.ComponentProps<'ul'>) {
  return (
    <ul className={cn('flex flex-col overflow-hidden rounded-xl bg-card shadow-cartao', className)} {...props}>
      {children}
    </ul>
  )
}

// Linha de Lista: ícone/anel à esquerda, título e subtítulo, conteúdo à direita e a seta quando a linha leva a outro
// lugar (href). `acoes` ficam fora do link (botões que não navegam).
export function LinhaLista({
  inicio,
  titulo,
  sub,
  fim,
  acoes,
  href,
  className,
}: {
  inicio?: ReactNode
  titulo: ReactNode
  sub?: ReactNode
  fim?: ReactNode
  acoes?: ReactNode
  href?: string
  className?: string
}) {
  const corpo = (
    <>
      {inicio && <div className="flex shrink-0 items-center">{inicio}</div>}
      <div className="flex min-w-0 flex-1 flex-col">
        <span className="truncate font-semibold">{titulo}</span>
        {sub && <span className="truncate text-nota text-muted-foreground">{sub}</span>}
      </div>
      {fim && <div className="flex shrink-0 items-center gap-3 text-nota text-muted-foreground">{fim}</div>}
    </>
  )
  return (
    <li className={cn('group/linha relative flex items-center gap-3 pr-3 pl-5 [&+&]:before:absolute [&+&]:before:top-0 [&+&]:before:right-0 [&+&]:before:left-5 [&+&]:before:h-px [&+&]:before:bg-linha', className)}>
      {href ? (
        <a href={href} className="-my-px flex min-w-0 flex-1 items-center gap-3 py-3 hover:opacity-80">
          {corpo}
          <ChevronRight className="size-4 shrink-0 text-terciario" aria-hidden />
        </a>
      ) : (
        <div className="flex min-w-0 flex-1 items-center gap-3 py-3">{corpo}</div>
      )}
      {acoes && <div className="flex shrink-0 items-center gap-2">{acoes}</div>}
    </li>
  )
}
