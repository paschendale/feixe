import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

type Aviso = { id: number; texto: string; tipo: 'ok' | 'erro' }
type Avisar = (texto: string, tipo?: Aviso['tipo']) => void

const Ctx = createContext<Avisar>(() => {})

// Avisos curtos no canto da tela (ação feita, recusa do banco). Somem sozinhos.
export function AvisosProvider({ children }: { children: ReactNode }) {
  const [avisos, setAvisos] = useState<Aviso[]>([])
  const avisar = useCallback<Avisar>((texto, tipo = 'ok') => {
    const id = Date.now() + Math.random()
    setAvisos((a) => [...a, { id, texto, tipo }])
    setTimeout(() => setAvisos((a) => a.filter((x) => x.id !== id)), tipo === 'erro' ? 8000 : 4000)
  }, [])
  return (
    <Ctx.Provider value={avisar}>
      {children}
      <div className="fixed right-4 bottom-4 z-50 flex w-96 flex-col gap-2">
        {avisos.map((a) => (
          <div
            key={a.id}
            role="status"
            className={cn(
              'rounded-md border px-4 py-3 text-sm shadow-md',
              a.tipo === 'erro' ? 'border-destructive bg-destructive text-white' : 'bg-background',
            )}
          >
            {a.texto}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export const useAvisar = () => useContext(Ctx)
