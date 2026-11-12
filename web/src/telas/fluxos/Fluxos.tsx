import { useState } from 'react'
import { Pencil, Plus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import type { Catalogo, FluxoCompleto } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { EditarFluxo } from './EditarFluxo'
import { NovoFluxo } from './NovoFluxo'

// Fluxos da unidade (B6): cada GGC monta o seu por projeto + tema, a partir do modelo da CCAR ou de outra unidade.
export default function Fluxos() {
  const { tem } = useSessao()
  const avisar = useAvisar()
  const supervisor = tem('supervisor')
  const { dados, erro } = useApi<{ itens: FluxoCompleto[] }>('/api/fluxos/completos', ['fluxo'])
  const { dados: catalogo } = useApi<Catalogo>('/api/catalogo', ['atividade'])
  const [editar, setEditar] = useState<FluxoCompleto | null>(null)
  const [novo, setNovo] = useState(false)

  async function alternar(f: FluxoCompleto) {
    try {
      await enviar(`/api/fluxos/${f.id}`, { ativo: !f.ativo }, 'PUT')
      avisar(`${f.nome}: ${f.ativo ? 'desativado' : 'ativado'}`)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  if (erro) return <p className="text-sm text-destructive">{erro}</p>
  if (!dados) return <p className="text-sm text-muted-foreground">Carregando…</p>
  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">Sequência de etapas por projeto e tema. O supervisor anda com cada folha por elas; nada avança sozinho.</p>
        {supervisor && catalogo && (
          <Button onClick={() => setNovo(true)}>
            <Plus /> Novo fluxo
          </Button>
        )}
      </div>
      {dados.itens.length === 0 && <p className="text-sm text-muted-foreground">Nenhum fluxo na unidade.</p>}
      {dados.itens.map((f) => (
        <Card key={f.id} className={cn('gap-3 px-5 py-4', !f.ativo && 'opacity-60')}>
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="flex items-center gap-2 text-[15px] font-semibold">
                {f.nome} {!f.ativo && <Badge variant="outline">inativo</Badge>}
              </h2>
              <p className="text-sm text-muted-foreground">
                {f.projeto} · {f.tema} · {f.uf} · {f.lotes} {f.lotes === 1 ? 'lote' : 'lotes'}
              </p>
            </div>
            {supervisor && (
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => alternar(f)}>
                  {f.ativo ? 'Desativar' : 'Ativar'}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditar(f)} disabled={!catalogo}>
                  <Pencil /> Editar
                </Button>
              </div>
            )}
          </div>
          <ol className="flex flex-wrap items-center gap-1.5 text-sm">
            {f.etapas.map((e, i) => (
              <li key={e.id} className="flex items-center gap-1.5">
                {i > 0 && <span className="text-muted-foreground">→</span>}
                <span className={cn('rounded-md border px-2 py-0.5', e.obrigatoria ? 'bg-accent' : 'border-dashed')} title={e.atividades.map((a) => a.nome).join('\n') || 'sem atividade'}>
                  {e.nome}
                  {e.repetivel && <span className="text-muted-foreground"> ↻</span>}
                  {e.fracao_critica != null && <span className="text-muted-foreground"> · {e.fracao_critica}%</span>}
                </span>
              </li>
            ))}
          </ol>
        </Card>
      ))}
      <p className="text-xs text-muted-foreground">Contorno tracejado: etapa opcional (pode ser pulada). ↻: repetível. Passe o mouse para ver as atividades.</p>
      {catalogo && <EditarFluxo fluxo={editar} catalogo={catalogo} fechar={() => setEditar(null)} />}
      {catalogo && (
        <NovoFluxo
          catalogo={catalogo}
          aberto={novo}
          fechar={(f) => {
            setNovo(false)
            if (f) setEditar(f)
          }}
        />
      )}
    </>
  )
}
