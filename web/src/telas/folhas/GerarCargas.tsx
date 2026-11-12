import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Lote, ResultadoGeracao } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { nivelGrade, num } from '@/lib/formato'
import { enviar } from '@/lib/useApi'

// Malha de cargas (B4, passo 2 do planejamento): prévia por folha (e no QGIS), depois gravar. Sem importação de malha:
// tudo pela grade estatística no nível da atividade da etapa (D-86).
export function GerarCargas({ lotes, fechar }: { lotes: Lote[]; fechar: (gravou: boolean) => void }) {
  const avisar = useAvisar()
  const [previa, setPrevia] = useState<ResultadoGeracao | null>(null)
  const [ocupado, setOcupado] = useState(false)
  const ids = lotes.map((l) => l.id_lote_etapa_atual).filter((x): x is number => x != null)

  useEffect(() => {
    if (!lotes.length) return
    setPrevia(null)
    enviar<ResultadoGeracao>('/api/cargas/gerar', { lote_etapas: ids, previa: true })
      .then(setPrevia)
      .catch((e) => avisar((e as Error).message, 'erro'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotes])

  async function gravar() {
    setOcupado(true)
    try {
      const r = await enviar<ResultadoGeracao>('/api/cargas/gerar', { lote_etapas: previa!.resultados.map((x) => x.id_lote_etapa), previa: false })
      const total = r.resultados.reduce((s, x) => s + x.gravadas, 0)
      avisar(`${num(total)} cargas gravadas em ${r.resultados.length} ${r.resultados.length === 1 ? 'folha' : 'folhas'}, disponíveis para atribuir.`)
      r.erros.forEach((e) => avisar(e.erro, 'erro'))
      fechar(true)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  const total = previa?.resultados.reduce((s, x) => s + x.celulas, 0) ?? 0
  return (
    <Dialog open={lotes.length > 0} onOpenChange={(v) => !v && fechar(false)}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Gerar cargas</DialogTitle>
          <DialogDescription>
            Células da grade estatística do IBGE com o centroide na folha, inteiras, no nível da atividade da etapa. A prévia aparece no QGIS
            como "Prévia de cargas".
          </DialogDescription>
        </DialogHeader>
        {!previa && <p className="text-sm text-muted-foreground">Calculando a prévia…</p>}
        {previa && (
          <div className="max-h-80 overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="pl-3">Folha</TableHead>
                  <TableHead>Etapa</TableHead>
                  <TableHead>Grade</TableHead>
                  <TableHead className="pr-3 text-right">Cargas</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {previa.resultados.map((x) => (
                  <TableRow key={x.id_lote_etapa}>
                    <TableCell className="tab pl-3 font-semibold">{x.folha_revisao}</TableCell>
                    <TableCell className="whitespace-normal">{x.etapa}</TableCell>
                    <TableCell>{nivelGrade(x.grade_nivel)}</TableCell>
                    <TableCell className="tab pr-3 text-right">{num(x.celulas)}</TableCell>
                  </TableRow>
                ))}
                {previa.erros.map((e) => (
                  <TableRow key={e.id_lote_etapa}>
                    <TableCell colSpan={4} className="pl-3 whitespace-normal text-destructive">
                      {e.erro}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
        {ids.length < lotes.length && (
          <p className="text-sm text-muted-foreground">{lotes.length - ids.length} lote(s) sem etapa atual ficaram de fora.</p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => fechar(false)}>
            Cancelar
          </Button>
          <Button onClick={gravar} disabled={!previa?.resultados.length || ocupado}>
            {ocupado ? 'Gravando…' : `Gravar ${num(total)} cargas`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
