import { useState } from 'react'
import { MousePointerSquareDashed } from 'lucide-react'
import { RotuloEstavel } from '@/components/painel'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import type { ResultadoCriacao } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { useSessao } from '@/lib/sessao'
import { enviar } from '@/lib/useApi'
import { EscolherFluxo } from './EscolherFluxo'
import { criadosComCargas, resumoCriacao } from './NovaFolha'

type Selecao = { camada: string; feicoes: number; wkt: string }

// Lote livre: polígono ad hoc (bacia, município, área desenhada) vindo da seleção da camada ativa no QGIS (B3).
export function NovoLoteLivre({ aberto, fechar }: { aberto: boolean; fechar: (criados?: number[]) => void }) {
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const [fluxo, setFluxo] = useState<number | null>(null)
  const [nome, setNome] = useState('')
  const [selecao, setSelecao] = useState<Selecao | null>(null)
  const [ocupado, setOcupado] = useState(false)

  async function lerSelecao() {
    try {
      setSelecao(await enviar<Selecao>('/api/qgis/selecao'))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  async function criar() {
    setOcupado(true)
    try {
      const r = await enviar<ResultadoCriacao>('/api/lotes', { tipo: 'livre', id_fluxo: fluxo, nome, wkt: selecao?.wkt })
      avisar(resumoCriacao(r), r.preparo?.erro ? 'erro' : undefined)
      setNome('')
      setSelecao(null)
      fechar(criadosComCargas(r))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <Dialog open={aberto} onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Novo lote livre</DialogTitle>
          <DialogDescription>
            Para unidades que não são folha (bacia, município). Selecione no QGIS as feições do polígono, na camada ativa.
          </DialogDescription>
        </DialogHeader>
        <EscolherFluxo valor={fluxo} mudar={(f) => setFluxo(f?.id ?? null)} />
        <div className="grid gap-1.5">
          <Label htmlFor="nome-lote">Nome</Label>
          <Input id="nome-lote" placeholder="ex.: Bacia do Paranoá" value={nome} onChange={(e) => setNome(e.target.value)} />
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" onClick={lerSelecao} disabled={!conectado}>
            <MousePointerSquareDashed /> Usar a seleção do QGIS
          </Button>
          <span className="text-sm text-muted-foreground">
            {selecao ? `${selecao.feicoes} ${selecao.feicoes === 1 ? 'feição' : 'feições'} de ${selecao.camada}` : 'Nenhum polígono ainda.'}
          </span>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => fechar()}>
            Cancelar
          </Button>
          <Button onClick={criar} disabled={!fluxo || !nome.trim() || !selecao || ocupado}>
            <RotuloEstavel ocupado={ocupado} rotulo="Criar o lote e gerar as cargas" rotuloOcupado="Criando e gerando as cargas…" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
