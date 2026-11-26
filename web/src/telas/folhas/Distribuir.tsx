import { useEffect, useMemo, useState } from 'react'
import { Colunas, RotuloEstavel } from '@/components/painel'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import type { PessoaDistribuir, SugestaoDistribuicao } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { num, plural } from '@/lib/formato'
import { enviar } from '@/lib/useApi'
import { cn } from '@/lib/utils'

type Destino = { tipo: 'agora' } | { tipo: 'fila'; posicao: number } | { tipo: 'ja' } | { tipo: 'fica' } | null
type Folha = SugestaoDistribuicao['folhas'][number]

const primeiro = (n: string | null | undefined) => (n ?? '').split(' ').slice(0, 2).join(' ')

function situacao(p: PessoaDistribuir) {
  const agora = p.pendentes ? `${num(p.pendentes)} pendentes` : 'sem carga'
  return p.na_fila ? `${agora} · ${p.na_fila} na fila` : agora
}

// Distribuir (D-109): uma folha por pessoa, sempre. Quem está sem carga recebe a folha agora, e a etapa começa; quem
// já tem, recebe na fila e pega quando terminar o que tem. O Feixe sugere (perfil da fase, quem tem menos nas mãos,
// nunca quem fez a etapa anterior da folha); o supervisor confere e troca o que quiser.
// Redistribuir (D-112): folha que já está com alguém aparece com "Deixar com Fulano"; escolher outra pessoa tira dela as
// cargas pendentes (as concluídas ficam com quem fez) e a folha segue a mesma regra: agora, se a pessoa está sem carga;
// senão, na fila.

const comQuem = (f: Folha) => f.com.map((p) => primeiro(p.nome)).join(', ')
// A escolha não muda nada: vazio, ou a única pessoa que já está com a folha.
const semMudanca = (f: Folha, c: string | undefined) => !c || (f.com.length === 1 && f.com[0].conta === c) || c === f.na_fila_de
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
  const distribuiveis = (dados?.folhas ?? []).filter((f) => f.a_atribuir > 0 || f.com.length > 0)
  const nada = (dados?.folhas ?? []).filter((f) => !f.a_atribuir && !f.com.length)
  const comAlguem = distribuiveis.filter((f) => f.com.length > 0).length
  // CQ (D3d): o que se distribui são as amostras (uma carga por célula sorteada), e quem recebe é um avaliador.
  const ehCq = (f: Folha) => f.fase === 'cq'
  const soCq = !!dados && (distribuiveis.length ? distribuiveis : dados.folhas).every(ehCq)
  const algumCq = !!dados && dados.folhas.some(ehCq)

  // O que vai acontecer, na ordem da lista: a primeira folha de quem está livre é dele agora, as outras vão para a fila.
  // Quem perde uma folha na redistribuição fica com menos pendentes (e pode ficar livre para receber outra).
  const destinos = useMemo(() => {
    const pendentes = new Map((dados?.pessoas ?? []).map((p) => [p.conta, p.pendentes]))
    for (const f of distribuiveis) {
      const c = escolha[f.id_lote_etapa]
      if (semMudanca(f, c)) continue
      for (const p of f.com) if (p.conta !== c) pendentes.set(p.conta, (pendentes.get(p.conta) ?? 0) - p.pendentes)
    }
    const livre = new Map((dados?.pessoas ?? []).map((p) => [p.conta, !pendentes.get(p.conta) && !p.na_fila]))
    const fila = new Map((dados?.pessoas ?? []).map((p) => [p.conta, p.na_fila]))
    const d: Record<number, Destino> = {}
    for (const f of distribuiveis) {
      const c = escolha[f.id_lote_etapa]
      if (!c) d[f.id_lote_etapa] = f.com.length ? { tipo: 'fica' } : null
      else if (c === f.na_fila_de) d[f.id_lote_etapa] = { tipo: 'ja' }
      else if (f.com.some((p) => p.conta === c)) d[f.id_lote_etapa] = f.com.length === 1 ? { tipo: 'fica' } : { tipo: 'agora' }
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

  const itens = distribuiveis.filter((f) => !semMudanca(f, escolha[f.id_lote_etapa]))
  const nTroca = itens.filter((f) => f.com.length > 0).length
  const nAgora = Object.values(destinos).filter((d) => d?.tipo === 'agora').length
  const nFila = Object.values(destinos).filter((d) => d?.tipo === 'fila').length
  const sem = distribuiveis.filter((f) => !escolha[f.id_lote_etapa] && !f.com.length).length

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
          <DialogTitle>
            Distribuir {soCq ? 'as amostras de ' : ''}
            {distribuiveis.length > 1 ? `${num(distribuiveis.length)} folhas` : soCq ? 'uma folha' : 'a folha'}
          </DialogTitle>
          <DialogDescription>
            {soCq
              ? 'Uma folha por avaliador: quem recebe fica com todas as amostras de CQ da folha. Quem está sem carga recebe agora e a etapa de CQ começa; quem já tem, recebe na fila. A sugestão evita quem trabalhou na folha antes (avaliação às cegas).'
              : 'Uma folha por pessoa. Quem está sem carga recebe agora e a etapa começa; quem já tem, recebe na fila e pega a folha quando terminar o que tem. A sugestão evita quem fez a etapa anterior da folha.'}
            {comAlguem > 0 && ' Folha que já está com alguém fica com a pessoa; escolha outra para redistribuir: as cargas pendentes saem de quem estava (as concluídas continuam dela).'}
          </DialogDescription>
        </DialogHeader>
        {/* Enquanto a sugestão chega, o espaço da tabela já fica reservado (uma linha por folha): o diálogo não salta. */}
        {!dados && (
          <div className="grid place-items-center rounded-md border text-sm text-muted-foreground" style={{ height: `min(${37 + 57 * lotes.length}px, 52vh)` }}>
            Montando a sugestão…
          </div>
        )}
        {dados && distribuiveis.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {soCq ? 'Nenhuma destas folhas tem amostras a distribuir: os planos de CQ ainda não foram criados ou as amostras já estão com avaliadores.' : 'Nenhuma destas folhas tem cargas a distribuir: abra a próxima etapa delas, que já sai com as cargas.'}
          </p>
        )}
        {dados && distribuiveis.length > 0 && (
          <div className="max-h-[52vh] overflow-auto rounded-md border">
            <table className="w-full table-fixed border-collapse text-sm">
              <Colunas larguras={['28%', '44%', undefined]} />
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
                    <tr key={f.id_lote_etapa} className="border-b border-linha last:border-0">
                      <td className="py-2 pr-2 pl-3">
                        <b className="tab">{f.folha_revisao}</b>
                        <span className="block text-xs text-muted-foreground">
                          {f.etapa} · {f.fase === 'correcao_inspecao' && f.cargas === 1 ? 'a folha inteira: tratar as ocorrências' : plural(f.a_atribuir + f.com.reduce((n, p) => n + p.pendentes, 0), ehCq(f) ? 'amostra' : 'carga', ehCq(f) ? 'amostras' : 'cargas')}
                        </span>
                      </td>
                      <td className="px-2 py-2">
                        <Select className="h-8 w-full text-[13px]" value={c ?? ''} onChange={(e) => setEscolha((x) => ({ ...x, [f.id_lote_etapa]: e.target.value }))} aria-label={`Quem recebe a ${f.folha_revisao}`}>
                          <option value="">{f.com.length ? `Deixar com ${comQuem(f)}` : 'Não distribuir agora'}</option>
                          {dados.pessoas.map((p) => (
                            <option key={p.conta} value={p.conta}>
                              {primeiro(p.nome)} · {situacao(p)}
                              {f.com.some((x) => x.conta === p.conta) ? ' · está com a folha' : f.anteriores.includes(p.conta) ? ' · fez a etapa anterior' : ''}
                            </option>
                          ))}
                        </Select>
                        {c && f.anteriores.includes(c) && <span className="mt-0.5 block text-xs text-[#8A5300]">Esta pessoa trabalhou na etapa anterior desta folha: a revisão deixa de ser às cegas.</span>}
                      </td>
                      <td className={cn('py-2 pr-3 pl-2 text-[13px]', d?.tipo === 'agora' && 'font-semibold text-ibge')}>
                        {d?.tipo === 'agora' && 'agora'}
                        {d?.tipo === 'fila' && `na fila (${d.posicao}ª)`}
                        {d?.tipo === 'ja' && `já está na fila de ${primeiro(pessoa.get(c)?.nome)}`}
                        {d?.tipo === 'fica' && <span className="text-muted-foreground">continua com {comQuem(f)}</span>}
                        {!d && <span className="text-muted-foreground">fica a atribuir</span>}
                        {d && d.tipo !== 'fica' && f.com.some((p) => p.conta !== c) && (
                          <span className="block text-xs text-muted-foreground">
                            sai de {f.com.filter((p) => p.conta !== c).map((p) => `${primeiro(p.nome)} (${plural(p.pendentes, 'pendente', 'pendentes')})`).join(', ')}
                          </span>
                        )}
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
            {algumCq ? 'Nada a distribuir' : 'Sem cargas a distribuir'}: {nada.map((f) => f.folha_revisao).join(', ')} (
            {nada.some((f) => f.cargas) ? (nada.every(ehCq) ? 'todas avaliadas' : 'todas concluídas') : nada.every(ehCq) ? 'sem amostras ainda' : 'a etapa não tem cargas'}).
          </p>
        )}
        <DialogFooter className="items-center gap-3 sm:justify-between">
          <span className="text-[13px] text-muted-foreground">
            {[nTroca && `${plural(nTroca, 'folha muda', 'folhas mudam')} de mão`, nAgora && `${plural(nAgora, 'pessoa recebe', 'pessoas recebem')} agora`, nFila && `${plural(nFila, 'folha vai', 'folhas vão')} para a fila`, sem && `${plural(sem, 'fica', 'ficam')} a atribuir`].filter(Boolean).join(' · ')}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => fechar(false)}>
              Depois
            </Button>
            <Button onClick={distribuir} disabled={!itens.length || ocupado}>
              <RotuloEstavel ocupado={ocupado} rotulo="Distribuir" rotuloOcupado="Distribuindo…" />
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
