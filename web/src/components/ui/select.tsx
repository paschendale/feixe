import * as React from 'react'
import { cn } from '@/lib/utils'

// Select nativo com o visual do Input: funciona igual em qualquer navegador das estações e não precisa de portal.
function Select({ className, ...props }: React.ComponentProps<'select'>) {
  return (
    <select
      className={cn(
        'h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:opacity-50',
        className,
      )}
      {...props}
    />
  )
}

export { Select }
