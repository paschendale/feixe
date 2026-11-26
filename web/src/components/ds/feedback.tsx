import type { ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { TOM, type Tom } from './cores'

// Estados e mensagens: selo, nota (aviso dentro da tela), vazio e carregando.

// Selo: um estado curto ao lado de um nome ("parada", "não conforme", "nova").
export function Selo({ tom = 'neutro', children, className, title }: { tom?: Tom; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn('inline-flex h-5 w-fit shrink-0 items-center gap-1 rounded-full px-2 text-rodape font-semibold whitespace-nowrap', TOM[tom].fundo, TOM[tom].texto, className)}>
      {children}
    </span>
  )
}

// Selo de uma cor de dado (status nacional): fundo na cor, texto claro ou escuro conforme `escuro`.
export function SeloCor({ cor, escuro, children, className }: { cor: string; escuro?: boolean; children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex h-5 w-fit shrink-0 items-center rounded-full px-2 text-rodape font-semibold whitespace-nowrap', className)} style={{ background: cor, color: escuro ? 'var(--primary-foreground)' : 'var(--dado-texto-claro)' }}>
      {children}
    </span>
  )
}

// Ponto colorido + texto (status nacional, conexão).
export function Ponto({ cor, children, className }: { cor: string; children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 whitespace-nowrap', className)}>
      <span className="size-2 shrink-0 rounded-full" style={{ background: cor }} />
      {children}
    </span>
  )
}

const ICONE: Record<Tom, typeof Info> = { neutro: Info, info: Info, sucesso: CheckCircle2, alerta: AlertTriangle, perigo: XCircle }

// Nota: mensagem dentro da tela (o que aconteceu, o que falta, uma restrição), num fundo suave do tom.
export function Nota({ tom = 'info', titulo, children, acao, className, semIcone }: { tom?: Tom; titulo?: ReactNode; children?: ReactNode; acao?: ReactNode; className?: string; semIcone?: boolean }) {
  const Icone = ICONE[tom]
  return (
    <div role={tom === 'perigo' ? 'alert' : 'status'} className={cn('flex items-start gap-3 rounded-xl px-4 py-3 text-nota', TOM[tom].fundo, className)}>
      {!semIcone && <Icone className={cn('mt-px size-4 shrink-0', TOM[tom].texto)} aria-hidden />}
      <div className="flex min-w-0 flex-1 flex-col gap-0.5 text-foreground">
        {titulo && <b className="font-semibold">{titulo}</b>}
        {children && <div className="text-texto-2">{children}</div>}
      </div>
      {acao && <div className="shrink-0 self-center">{acao}</div>}
    </div>
  )
}

// Estado vazio: o que não há e o que fazer (dentro de um Bloco, de uma Lista ou de uma Tabela).
export function Vazio({ children, acao, className }: { children: ReactNode; acao?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center gap-2 px-6 py-8 text-center text-muted-foreground', className)}>
      <span className="max-w-[520px]">{children}</span>
      {acao}
    </div>
  )
}

export function Carregando({ erro }: { erro?: string | null }) {
  return erro ? (
    <Nota tom="perigo">{erro}</Nota>
  ) : (
    <p className="text-muted-foreground" role="status">
      Carregando…
    </p>
  )
}
