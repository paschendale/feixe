import * as React from 'react'
import { Popover as P } from 'radix-ui'
import { cn } from '@/lib/utils'

// Ação que pede uma escolha (para quem, qual folha) abre ancorada no botão, por cima da tabela: a célula nunca muda
// de conteúdo nem de largura.
const Popover = P.Root
const PopoverTrigger = P.Trigger

function PopoverContent({ className, align = 'end', sideOffset = 6, ...props }: React.ComponentProps<typeof P.Content>) {
  return (
    <P.Portal>
      <P.Content
        align={align}
        sideOffset={sideOffset}
        className={cn('z-50 flex w-80 flex-col gap-3 rounded-lg bg-popover p-4 text-popover-foreground shadow-flutuante outline-none', className)}
        {...props}
      />
    </P.Portal>
  )
}

export { Popover, PopoverTrigger, PopoverContent }
