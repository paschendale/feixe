import { useEffect, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import type { PessoaDistribuir, SugestaoDistribuicao } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { num, plural } from '@/lib/formato'
import { enviar } from '@/lib/useApi'
import { cn } from '@/lib/utils'

type Destino = { tipo: 'agora' } | { tipo: 'fila'; posicao: number } | { tipo: 'ja' } | null

const primeiro = (n: string | null | undefined) => (n ?? '').split(' ').slice(0, 2).join(' ')

function situacao(p: PessoaDistribuir) {
  const agora = p.pendentes ? `${num(p.pendentes)} pendentes` : 'sem carga'
  return p.na_fila ? `${agora} · ${p.na_fila} na fila` : agora
}

// Distribuir (D-109): uma folha por pessoa, sempre. Quem está sem carga recebe a folha agora, e a etapa começa; quem
// já tem, recebe na fila e pega quando terminar o que tem. O Feixe sugere (perfil da fase, quem tem menos nas mãos,
// nunca quem fez a etapa anterior da folha); o supervisor confere e troca o que quiser.
export function Distribuir({ lotes, fechar }: { lotes: number[]; fechar: (feito: boolean) => void }) {
  const avisar = useAvisar()
  const [dados, setDados] = useState<SugestaoDistribuicao | null>(null)
  const [escolha, setEscolha] = useState<Record<number, string>>({})
  const [ocupado, setOcupado] = useState(false)

  useEffect(() => {
    if (!lotes.length) return
    setDados(null)
    enviar<SugestaoDistribuicao>('/api/distribuir/sugestao', { lotes })
      .then((d) => {
        setDados(d)
        setEscolha(Object.fromEntries(d.folhas.map((f) => [f.id_lote_etapa, f.sugerida ?? ''])))
      })
      .catch((e) => avisar((e as Error).message, 'erro'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotes])

  const pessoa = useMemo(() => new Map((dados?.pessoas ?? []).map((p) => [p.conta, p])), [dados])
  const distribuiveis = (dados?.folhas ?? []).filter((f) => f.a_atribuir > 0)
  const nada = (dados?.folhas ?? []).filter((f) => !f.a_atribuir)

  // O que vai acontecer, na ordem da lista: a primeira folha de quem está livre é dele agora, as outras vão para a fila.
  const destinos = useMemo(() => {
    const livre = new Map((dados?.pessoas ?? []).map((p) => [p.conta, !p.pendentes && !p.na_fila]))
    const fila = new Map((dados?.pessoas ?? []).map((p) => [p.conta, p.na_fila]))
    const d: Record<number, Destino> = {}
    for (const f of distribuiveis) {
      const c = escolha[f.id_lote_etapa]
      if (!c) d[f.id_lote_etapa] = null
      else if (c === f.na_fila_de) d[f.id_lote_etapa] = { tipo: 'ja' }
      else if (livre.get(c)) {
        d[f.id_lote_etapa] = { tipo: 'agora' }
        livre.set(c, false)
      } else {
        fila.set(c, (fila.get(c) ?? 0) + 1)
        d[f.id_lote_etapa] = { tipo: 'fila', posicao: fila.get(c)! }
      }
    }
    return d
  }, [dados, escolha, distribuiveis])

  const itens = distribuiveis.filter((f) => escolha[f.id_lote_etapa] && escolha[f.id_lote_etapa] !== f.na_fila_de)
  const nAgora = Object.values(destinos).filter((d) => d?.tipo === 'agora').length
  const nFila = Object.values(destinos).filter((d) => d?.tipo === 'fila').length
  const sem = distribuiveis.filter((f) => !escolha[f.id_lote_etapa]).length

  async function distribuir() {
    setOcupado(true)
    try {
      const r = await enviar<{ agora: unknown[]; na_fila: unknown[]; erros: { id_lote_etapa: number; erro: string }[] }>('/api/distribuir', {
        itens: itens.map((f) => ({ id_lote_etapa: f.id_lote_etapa, responsavel: escolha[f.id_lote_etapa] })),
      })
      const partes = [r.agora.length && `${plural(r.agora.length, 'folha entregue', 'folhas entregues')} agora (a etapa começou)`, r.na_fila.length && `${plural(r.na_fila.length, 'folha', 'folhas')} na fila`]
      avisar(`Distribuído: ${partes.filter(Boolean).join(', ')}.`)
      r.erros.forEach((e) => avisar(e.erro, 'erro'))
      fechar(true)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <Dialog open={lotes.length > 0} onOpenChange={(v) => !v && fechar(false)}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Distribuir {distribuiveis.length > 1 ? `${num(distribuiveis.length)} folhas` : 'a folha'}</DialogTitle>
          <DialogDescription>
            Uma folha por pessoa. Quem está sem carga recebe agora e a etapa começa; quem já tem, recebe na fila e pega a folha quando terminar o que tem. A sugestão evita quem fez a etapa anterior da folha.
          </DialogDescription>
        </DialogHeader>
        {!dados && <p className="text-sm text-muted-foreground">Montando a sugestão…</p>}
        {dados && distribuiveis.length === 0 && <p className="text-sm text-muted-foreground">Nenhuma destas folhas tem cargas a distribuir.</p>}
        {dados && distribuiveis.length > 0 && (
          <div className="max-h-[52vh] overflow-auto rounded-md border">
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 bg-card">
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="border-b py-2 pr-2 pl-3 font-medium">Folha</th>
                  <th className="border-b px-2 py-2 font-medium">Para</th>
                  <th className="border-b py-2 pr-3 pl-2 font-medium">Recebe</th>
                </tr>
              </thead>
              <tbody>
                {distribuiveis.map((f) => {
                  const c = escolha[f.id_lote_etapa]
                  const d = destinos[f.id_lote_etapa]
                  return (
                    <tr key={f.id_lote_etapa} className="border-b border-[#EEF1F4] last:border-0">
                      <td className="py-2 pr-2 pl-3">
                        <b className="tab">{f.folha_revisao}</b>
                        <span className="block text-xs text-muted-foreground">
                          {f.etapa} · {plural(f.a_atribuir, 'carga', 'cargas')}
                        </span>
                      </td>
                      <td className="px-2 py-2">
                        <Select className="h-8 w-full min-w-[240px] text-[13px]" value={c ?? ''} onChange={(e) => setEscolha((x) => ({ ...x, [f.id_lote_etapa]: e.target.value }))} aria-label={`Quem recebe a ${f.folha_revisao}`}>
                          <option value="">Não distribuir agora</option>
                          {dados.pessoas.map((p) => (
                            <option key={p.conta} value={p.conta}>
                              {primeiro(p.nome)} · {situacao(p)}
                              {f.anteriores.includes(p.conta) ? ' · fez a etapa anterior' : ''}
                            </option>
                          ))}
                        </Select>
                        {c && f.anteriores.includes(c) && <span className="mt-0.5 block text-xs text-[#8A5300]">Esta pessoa trabalhou na etapa anterior desta folha: a revisão deixa de ser às cegas.</span>}
                      </td>
                      <td className={cn('py-2 pr-3 pl-2 text-[13px]', d?.tipo === 'agora' && 'font-semibold text-ibge')}>
                        {d?.tipo === 'agora' && 'agora'}
                        {d?.tipo === 'fila' && `na fila (${d.posicao}ª)`}
                        {d?.tipo === 'ja' && `já está na fila de ${primeiro(pessoa.get(c)?.nome)}`}
                        {!d && <span className="text-muted-foreground">fica a atribuir</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {nada.length > 0 && (
          <p className="text-xs text-muted-foreground">
            Sem cargas a distribuir: {nada.map((f) => f.folha_revisao).join(', ')} ({nada.some((f) => f.cargas) ? 'já estão com alguém' : 'a etapa não tem cargas'}).
          </p>
        )}
        <DialogFooter className="items-center gap-3 sm:justify-between">
          <span className="text-[13px] text-muted-foreground">
            {[nAgora && `${plural(nAgora, 'pessoa recebe', 'pessoas recebem')} agora`, nFila && `${plural(nFila, 'folha vai', 'folhas vão')} para a fila`, sem && `${plural(sem, 'fica', 'ficam')} a atribuir`].filter(Boolean).join(' · ')}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => fechar(false)}>
              Depois
            </Button>
            <Button onClick={distribuir} disabled={!itens.length || ocupado}>
              {ocupado ? 'Distribuindo…' : 'Distribuir'}
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
