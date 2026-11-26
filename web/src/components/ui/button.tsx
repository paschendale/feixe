import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"
import { Slot } from "radix-ui"

// Botões do design system. Uma ação primária (default) por área; as demais em tinted (ação secundária em destaque),
// outline (bordered, neutra), secondary (cinza), ghost (na linha) ou link.
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md text-corpo font-medium whitespace-nowrap transition-[background,box-shadow,opacity] outline-none select-none focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-45 aria-invalid:ring-destructive/20 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-controle hover:bg-primary/90 active:bg-primary/80",
        tinted: "bg-primary-suave text-primary hover:bg-primary/15 active:bg-primary/20",
        destructive: "bg-destructive text-white shadow-controle hover:bg-destructive/90 focus-visible:ring-destructive/20",
        "destructive-tinted": "bg-perigo-suave text-perigo hover:bg-destructive/15",
        outline: "bg-card text-foreground shadow-controle hover:bg-preenchimento-2 active:bg-preenchimento",
        secondary: "bg-secondary text-secondary-foreground hover:bg-preenchimento active:bg-preenchimento",
        ghost: "text-foreground hover:bg-preenchimento-2 active:bg-preenchimento",
        link: "h-auto px-0 text-primary underline-offset-4 hover:underline has-[>svg]:px-0",
      },
      size: {
        default: "h-8 px-3.5 has-[>svg]:px-3",
        xs: "h-6 gap-1 rounded-sm px-2 text-rodape has-[>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-7 gap-1 px-2.5 text-nota has-[>svg]:px-2",
        lg: "h-10 rounded-lg px-5 text-corpo has-[>svg]:px-4",
        icon: "size-8",
        "icon-xs": "size-6 rounded-sm [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-7",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean
  }) {
  const Comp = asChild ? Slot.Root : "button"

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
