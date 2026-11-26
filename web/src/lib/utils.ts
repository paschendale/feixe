import { clsx, type ClassValue } from "clsx"
import { extendTailwindMerge } from "tailwind-merge"

// O tailwind-merge precisa conhecer a escala de texto do design system (index.css): sem isso, `text-nota` e
// `text-primary` parecem duas cores e uma some.
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["titulo-grande", "titulo-1", "titulo-2", "titulo-3", "corpo", "nota", "rodape", "legenda", "numero", "lede"] }],
    },
  },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
