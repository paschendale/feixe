import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'
import { CheckCircle2, XCircle } from 'lucide-react'

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
      <div className="fixed right-4 bottom-4 z-50 flex w-96 max-w-[calc(100%-2rem)] flex-col gap-2">
        {avisos.map((a) => (
          <div
            key={a.id}
            role="status"
            className="flex items-start gap-2.5 rounded-xl bg-card/95 px-4 py-3 text-nota shadow-flutuante backdrop-blur"
          >
            {a.tipo === 'erro' ? <XCircle className="mt-px size-4 shrink-0 text-perigo" aria-hidden /> : <CheckCircle2 className="mt-px size-4 shrink-0 text-sucesso" aria-hidden />}
            <span>{a.texto}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}

export const useAvisar = () => useContext(Ctx)
