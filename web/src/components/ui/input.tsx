import * as React from "react"
import { cn } from "@/lib/utils"

// Campo de texto: fundo branco, fio fino, anel azul suave no foco.
export const campoBase =
  "w-full min-w-0 rounded-md border border-input bg-card text-corpo text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-terciario focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/30 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-destructive/20"

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        campoBase,
        "h-8 px-2.5 selection:bg-primary selection:text-primary-foreground file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-nota file:font-medium file:text-foreground",
        className
      )}
      {...props}
    />
  )
}

export { Input }
