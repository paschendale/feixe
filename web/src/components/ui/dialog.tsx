import * as React from 'react'
import { Dialog as D } from 'radix-ui'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

const Dialog = D.Root

function DialogContent({ className, children, ...props }: React.ComponentProps<typeof D.Content>) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/25 backdrop-blur-[2px]" />
      <D.Content
        className={cn(
          'fixed top-1/2 left-1/2 z-50 grid max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-5 overflow-y-auto rounded-2xl bg-card p-6 shadow-flutuante outline-none',
          className,
        )}
        {...props}
      >
        {children}
        <D.Close className="absolute top-4 right-4 grid size-7 place-items-center rounded-full bg-preenchimento-2 text-muted-foreground hover:bg-preenchimento hover:text-foreground" aria-label="Fechar">
          <X className="size-3.5" />
        </D.Close>
      </D.Content>
    </D.Portal>
  )
}
function DialogHeader({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-col gap-1 pr-8', className)} {...props} />
}
function DialogFooter({ className, ...props }: React.ComponentProps<'div'>) {
  return <div className={cn('flex flex-wrap justify-end gap-2 pt-1', className)} {...props} />
}
function DialogTitle({ className, ...props }: React.ComponentProps<typeof D.Title>) {
  return <D.Title className={cn('text-titulo-2 font-semibold', className)} {...props} />
}
function DialogDescription({ className, ...props }: React.ComponentProps<typeof D.Description>) {
  return <D.Description className={cn('text-nota text-muted-foreground', className)} {...props} />
}

export { Dialog, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription }
