import * as React from 'react'
import { cn } from '@/lib/utils'
import { campoBase } from './input'

function Textarea({ className, ...props }: React.ComponentProps<'textarea'>) {
  return <textarea className={cn(campoBase, 'min-h-16 px-2.5 py-2', className)} {...props} />
}

export { Textarea }
