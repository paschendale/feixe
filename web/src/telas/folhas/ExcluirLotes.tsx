import { useEffect, useState } from 'react'
import { Nota, RotuloEstavel } from '@/components/ds'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useAvisar } from '@/lib/avisos'
import { lista, num, plural } from '@/lib/formato'
import { enviar } from '@/lib/useApi'

type Item = { id_lote: number; folha_revisao: string; tipo: string; cargas: number; com_alguem: number; erro: string | null }
const nomes = (xs: Item[]) => (xs.length <= 8 ? lista(xs.map((i) => i.folha_revisao)) : `${lista(xs.slice(0, 6).map((i) => i.folha_revisao))} e mais ${num(xs.length - 6)}`)

// Excluir folhas e lotes criados por engano (D-155), da gaveta ou da seleção na lista. Só sem trabalho feito (nenhuma
// carga concluída, amostra avaliada ou ocorrência): a prévia diz o que sai e o que fica de fora, com o motivo, e só a
// confirmação apaga. Saem junto as cargas, os planos de CQ, a fila e o histórico.
export function ExcluirLotes({ lotes, fechar }: { lotes: number[]; fechar: (excluidos: number[]) => void }) {
  const avisar = useAvisar()
  const [itens, setItens] = useState<Item[] | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const chave = lotes.join(',')

  useEffect(() => {
    setItens(null)
    if (!chave) return
    let vivo = true
    enviar<{ itens: Item[] }>('/api/lotes/excluir', { lotes: chave.split(',').map(Number), previa: true })
      .then((r) => vivo && setItens(r.itens))
      .catch((e) => {
        avisar((e as Error).message, 'erro')
        fechar([])
      })
    return () => {
      vivo = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chave])

  const saem = (itens ?? []).filter((i) => !i.erro)
  const ficam = (itens ?? []).filter((i) => i.erro)
  const cargas = saem.reduce((n, i) => n + i.cargas, 0)
  const comAlguem = saem.filter((i) => i.com_alguem > 0)

  async function excluir() {
    setOcupado(true)
    try {
      const r = await enviar<{ excluidos: { id_lote: number }[]; erros: { id_lote: number; erro: string }[] }>('/api/lotes/excluir', { lotes: saem.map((i) => i.id_lote), previa: false })
      avisar(`${plural(r.excluidos.length, 'excluída', 'excluídas')}: ${nomes(saem.filter((i) => r.excluidos.some((x) => x.id_lote === i.id_lote)))}.`)
      if (r.erros.length) avisar(r.erros.map((e) => e.erro).join('; '), 'erro')
      fechar(r.excluidos.map((x) => x.id_lote))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <Dialog open={lotes.length > 0} onOpenChange={(v) => !v && fechar([])}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Excluir {saem.length === 1 ? saem[0].folha_revisao : plural(saem.length || lotes.length, 'folha', 'folhas')}</DialogTitle>
          <DialogDescription>Para folhas e lotes criados por engano, antes de qualquer trabalho. Saem junto as passagens, as cargas, os planos de CQ, a fila e o histórico. Não dá para desfazer.</DialogDescription>
        </DialogHeader>
        {!itens && <p className="text-muted-foreground">Conferindo…</p>}
        {itens && saem.length > 0 && (
          <p>
            Sai{saem.length === 1 ? '' : 'em'} {nomes(saem)}, com {plural(cargas, 'carga', 'cargas')}.
          </p>
        )}
        {comAlguem.length > 0 && (
          <Nota tom="alerta">
            {nomes(comAlguem)} já {comAlguem.length === 1 ? 'tem' : 'têm'} cargas com alguém: elas somem do QGIS dessas pessoas na próxima sincronização.
          </Nota>
        )}
        {ficam.length > 0 && (
          <Nota tom="info">
            Ficam: {ficam.map((i) => `${i.folha_revisao} (${i.erro})`).join('; ')}.
          </Nota>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => fechar([])}>
            Cancelar
          </Button>
          <Button variant="destructive" disabled={!saem.length || ocupado} onClick={excluir}>
            <RotuloEstavel ocupado={ocupado} rotulo={saem.length === 1 ? `Excluir ${saem[0].folha_revisao}` : `Excluir ${plural(saem.length, 'folha', 'folhas')}`} rotuloOcupado="Excluindo…" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
