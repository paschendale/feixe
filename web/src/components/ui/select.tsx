import * as React from 'react'
import { cn } from '@/lib/utils'
import { campoBase } from './input'

// Select nativo com o visual do Input: funciona igual em qualquer navegador das estações e não precisa de portal.
function Select({ className, ...props }: React.ComponentProps<'select'>) {
  return <select className={cn(campoBase, 'h-8 pr-7 pl-2.5', className)} {...props} />
}

export { Select }
