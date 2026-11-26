import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { Campo, Nota, RotuloEstavel } from '@/components/ds'
import type { ItemAvanco, ResultadoAvanco } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { lista, num, plural } from '@/lib/formato'
import { enviar } from '@/lib/useApi'
import { comCargas, resumoPreparo } from './preparo'

const nomes = (xs: ItemAvanco[]) => (xs.length <= 8 ? lista(xs.map((i) => i.folha_revisao)) : `${lista(xs.slice(0, 6).map((i) => i.folha_revisao))} e mais ${num(xs.length - 6)}`)

// Abrir a próxima etapa em várias folhas (D-109), com confirmação: por grupo, a etapa que termina e a que abre. A folha
// com a etapa em andamento conclui essa etapa; as cargas da etapa nova saem na hora e a distribuição abre em seguida.
export function ProximaEtapa({ lotes, fechar }: { lotes: number[]; fechar: (abertas?: number[]) => void }) {
  const avisar = useAvisar()
  const [itens, setItens] = useState<ItemAvanco[] | null>(null)
  const [obs, setObs] = useState('')
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    if (!lotes.length) return
    setItens(null)
    setObs('')
    enviar<{ itens: ItemAvanco[] }>('/api/lotes/avancar', { lotes, previa: true })
      .then((r) => setItens(r.itens))
      .catch((e) => avisar((e as Error).message, 'erro'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotes])

  const validos = (itens ?? []).filter((i) => !i.erro)
  const recusados = (itens ?? []).filter((i) => i.erro)
  const grupos = new Map<string, ItemAvanco[]>()
  for (const i of validos) {
    const k = `${i.tema}|${i.etapa}|${i.proxima}|${i.concluir}`
    grupos.set(k, [...(grupos.get(k) ?? []), i])
  }
  const comPendentes = validos.filter((i) => i.concluir && i.pendentes > 0)
  // Correção de inspeção (D5): folhas com ocorrências ainda não tratadas (a carga da folha conta nas pendentes).
  const comATratar = validos.filter((i) => i.concluir && i.a_tratar > 0)
  const unica = new Set(validos.map((i) => i.proxima)).size === 1 ? validos[0]?.proxima : null

  async function confirmar() {
    setOcupado(true)
    try {
      const r = await enviar<ResultadoAvanco>('/api/lotes/avancar', { lotes: validos.map((i) => i.id_lote), observacao: obs, previa: false })
      const etapas = lista([...new Set(r.abertas.map((a) => a.etapa))])
      avisar([r.abertas.length && `${etapas} aberta em ${plural(r.abertas.length, 'folha', 'folhas')}.`, resumoPreparo(r.preparo)].filter(Boolean).join(' '))
      r.erros.forEach((e) => avisar(e.erro, 'erro'))
      const prontas = comCargas(r.preparo)
      fechar(r.abertas.filter((a) => prontas.has(a.id_lote_etapa)).map((a) => a.id_lote))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <Dialog open={lotes.length > 0} onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Abrir a próxima etapa</DialogTitle>
          <DialogDescription>Confira o que muda em cada folha. As cargas da etapa nova são geradas na hora, e a distribuição abre em seguida.</DialogDescription>
        </DialogHeader>
        {/* Mesma altura mínima enquanto confere e depois: o diálogo não salta quando a conferência chega. */}
        {!itens && <div className="grid min-h-[200px] place-items-center rounded-xl bg-preenchimento-2 text-muted-foreground">Conferindo as folhas…</div>}
        {itens && (
          <div className="flex max-h-[50vh] min-h-[200px] flex-col gap-3 overflow-auto">
            {[...grupos.values()].map((g) => {
              const i = g[0]
              return (
                <div key={`${i.tema}${i.etapa}${i.proxima}${i.concluir}`} className="rounded-xl bg-preenchimento-2 px-4 py-3">
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <b>{plural(g.length, 'folha', 'folhas')}</b>
                    <span className="text-nota text-muted-foreground">{i.tema}</span>
                  </div>
                  <p className="mt-1">
                    {i.concluir ? (
                      <>
                        conclui <b>{i.etapa}</b> e abre <b className="text-primary">{i.proxima}</b>
                      </>
                    ) : (
                      <>
                        {i.etapa ? `${i.etapa} já terminou; ` : ''}abre <b className="text-primary">{i.proxima}</b>
                      </>
                    )}
                  </p>
                  <p className="tab mt-1 text-nota text-muted-foreground">{nomes(g)}</p>
                </div>
              )
            })}
            {comPendentes.length > 0 && (
              <Nota tom="alerta">
                {plural(comPendentes.length, 'folha ainda tem', 'folhas ainda têm')} cargas pendentes ({nomes(comPendentes)}: {num(comPendentes.reduce((s, i) => s + i.pendentes, 0))} cargas). Elas ficam na etapa concluída e ninguém mais trabalha nelas.
              </Nota>
            )}
            {comATratar.length > 0 && (
              <Nota tom="alerta">
                Na correção de inspeção, {plural(comATratar.length, 'folha ainda tem', 'folhas ainda têm')} ocorrências por tratar ({nomes(comATratar)}: {num(comATratar.reduce((s, i) => s + i.a_tratar, 0))}). Concluir a etapa encerra a varredura assim mesmo.
              </Nota>
            )}
            {recusados.length > 0 && (
              <div className="text-nota">
                <b>Não {recusados.length === 1 ? 'anda' : 'andam'}:</b>
                <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                  {recusados.map((i) => (
                    <li key={i.id_lote}>
                      <span className="tab text-foreground">{i.folha_revisao}</span>: {i.erro}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
        {validos.length > 0 && (
          <Campo rotulo="Observação (opcional, vai para o histórico de cada folha)">
            <Textarea rows={2} value={obs} onChange={(e) => setObs(e.target.value)} placeholder="Ex.: aquisição conferida, segue para a revisão" />
          </Campo>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => fechar()}>
            Cancelar
          </Button>
          <Button disabled={!validos.length || ocupado} onClick={confirmar}>
            <RotuloEstavel ocupado={ocupado} rotulo={`Abrir ${unica ?? 'a próxima etapa'} em ${plural(validos.length, 'folha', 'folhas')}`} rotuloOcupado="Abrindo…" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
