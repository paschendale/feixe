import { useEffect, useState } from 'react'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { RotuloEstavel } from '@/components/ds'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import type { Catalogo, EtapaFluxo, FluxoCompleto } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { enviar } from '@/lib/useApi'
import { LQAS, NIVEIS, pct } from '../supervisao/PlanosCQ'

// Editor das etapas de um fluxo da unidade: ordem, fase, nome, obrigatória, repetível, conta revisão, o padrão dos planos
// de CQ (nível de inspeção, LQA e fração crítica, só CQ, D-135) e as atividades de cada etapa (do catálogo, do projeto,
// tema e fase do fluxo). Etapa com passagens não sai.
export function EditarFluxo({ fluxo, catalogo, fechar }: { fluxo: FluxoCompleto | null; catalogo: Catalogo; fechar: () => void }) {
  const avisar = useAvisar()
  const [nome, setNome] = useState('')
  const [etapas, setEtapas] = useState<EtapaFluxo[]>([])
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => {
    if (fluxo) {
      setNome(fluxo.nome)
      setEtapas(fluxo.etapas.map((e) => ({ ...e })))
    }
  }, [fluxo])
  if (!fluxo) return null

  const mudar = (i: number, m: Partial<EtapaFluxo>) => setEtapas((xs) => xs.map((x, k) => (k === i ? { ...x, ...m } : x)))
  const mover = (i: number, d: number) =>
    setEtapas((xs) => {
      const ys = [...xs]
      ;[ys[i], ys[i + d]] = [ys[i + d], ys[i]]
      return ys
    })
  const ativs = (fase: string) =>
    catalogo.atividades.filter((a) => a.ativo && a.cod_projeto === fluxo.cod_projeto && a.id_tema === fluxo.id_tema && a.fase === fase)

  async function salvar() {
    setOcupado(true)
    try {
      await enviar(
        `/api/fluxos/${fluxo!.id}`,
        {
          nome,
          etapas: etapas.map((e) => {
            const cq = e.fase === 'cq'
            return { ...e, atividades: e.atividades.map((a) => a.id), fracao_critica: cq ? e.fracao_critica : null, nivel_inspecao: cq ? e.nivel_inspecao : null, lqa: cq ? e.lqa : null }
          }),
        },
        'PUT',
      )
      avisar(`Fluxo salvo: ${nome}`)
      fechar()
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <Dialog open={!!fluxo} onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-h-[90vh] max-w-4xl overflow-auto">
        <DialogHeader>
          <DialogTitle>Editar fluxo</DialogTitle>
          <DialogDescription>
            {fluxo.projeto} · {fluxo.tema} · {fluxo.uf}. O supervisor anda com o lote por estas etapas; o Feixe só sugere a próxima.
          </DialogDescription>
        </DialogHeader>
        <Input value={nome} onChange={(e) => setNome(e.target.value)} aria-label="Nome do fluxo" />
        <ol className="flex flex-col gap-3">
          {etapas.map((e, i) => {
            const usada = !!e.passagens
            return (
              <li key={e.id ?? `n${i}`} className="grid grid-cols-[28px_1fr_auto] gap-3 rounded-xl border border-linha p-3">
                <span className="tab pt-2 font-semibold text-muted-foreground">{i + 1}.</span>
                <div className="flex flex-col gap-2">
                  <div className="grid grid-cols-[1fr_200px] gap-2">
                    <Input value={e.nome} onChange={(x) => mudar(i, { nome: x.target.value })} aria-label="Nome da etapa" />
                    <Select
                      value={e.fase}
                      disabled={usada}
                      onChange={(x) => mudar(i, { fase: x.target.value, atividades: [], fracao_critica: null, nivel_inspecao: x.target.value === 'cq' ? 'II' : null, lqa: x.target.value === 'cq' ? 4 : null })}
                      aria-label="Fase"
                    >
                      {catalogo.fases.map((f) => (
                        <option key={f.codigo} value={f.codigo}>
                          {f.nome}
                        </option>
                      ))}
                    </Select>
                  </div>
                  <div className="flex flex-wrap items-center gap-4">
                    {(
                      [
                        ['obrigatoria', 'Obrigatória'],
                        ['repetivel', 'Repetível'],
                        ['conta_revisao', 'Conta revisão'],
                      ] as const
                    ).map(([k, rot]) => (
                      <label key={k} className="flex items-center gap-1.5">
                        <input type="checkbox" checked={e[k]} onChange={(x) => mudar(i, { [k]: x.target.checked })} /> {rot}
                      </label>
                    ))}
                    {usada && <span className="text-rodape text-muted-foreground">{e.passagens} passagens</span>}
                  </div>
                  {e.fase === 'cq' && (
                    <div className="flex flex-col gap-1.5 rounded-xl bg-preenchimento-2 p-2.5">
                      <div className="flex flex-wrap items-center gap-4">
                        <label className="flex items-center gap-1.5">
                          Nível de inspeção
                          <Select className="h-7 w-24" value={e.nivel_inspecao ?? ''} onChange={(x) => mudar(i, { nivel_inspecao: x.target.value || null })}>
                            <option value="">—</option>
                            {NIVEIS.map((n) => (
                              <option key={n} value={n}>
                                {n}
                              </option>
                            ))}
                          </Select>
                        </label>
                        <label className="flex items-center gap-1.5">
                          LQA
                          <Select className="h-7 w-24" value={e.lqa != null ? String(e.lqa) : ''} onChange={(x) => mudar(i, { lqa: x.target.value ? Number(x.target.value) : null })}>
                            <option value="">—</option>
                            {LQAS.map((v) => (
                              <option key={v} value={String(v)}>
                                {pct(v)}
                              </option>
                            ))}
                          </Select>
                        </label>
                        <label className="flex items-center gap-1.5">
                          Fração crítica
                          <Input
                            className="h-7 w-20"
                            type="number"
                            step="0.1"
                            placeholder="4"
                            value={e.fracao_critica ?? ''}
                            onChange={(x) => mudar(i, { fracao_critica: x.target.value ? Number(x.target.value) : null })}
                          />
                          %
                        </label>
                      </div>
                      <span className="text-rodape text-muted-foreground">
                        {e.nivel_inspecao && e.lqa != null
                          ? 'Ao abrir a etapa, o Feixe sorteia as amostras de cada atividade e gera as cargas, com este padrão; o supervisor pode trocar os parâmetros na gaveta do lote enquanto nada foi avaliado.'
                          : 'Sem nível e LQA, a etapa abre sem amostras e o supervisor cria os planos na gaveta de cada lote.'}{' '}
                        Fração crítica vazia: a de cada elemento.
                      </span>
                    </div>
                  )}
                  <div className="flex flex-wrap gap-x-4 gap-y-1">
                    {ativs(e.fase).length === 0 && <span className="text-rodape text-muted-foreground">Nenhuma atividade desta fase no catálogo para o tema.</span>}
                    {ativs(e.fase).map((a) => (
                      <label key={a.id} className="flex items-center gap-1.5">
                        <input
                          type="checkbox"
                          checked={e.atividades.some((x) => x.id === a.id)}
                          onChange={(x) =>
                            mudar(i, { atividades: x.target.checked ? [...e.atividades, { id: a.id, nome: a.nome }] : e.atividades.filter((y) => y.id !== a.id) })
                          }
                        />
                        {a.medida ?? a.nome}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col gap-1">
                  <Button size="icon-xs" variant="ghost" disabled={i === 0} onClick={() => mover(i, -1)} aria-label="Subir">
                    <ArrowUp />
                  </Button>
                  <Button size="icon-xs" variant="ghost" disabled={i === etapas.length - 1} onClick={() => mover(i, 1)} aria-label="Descer">
                    <ArrowDown />
                  </Button>
                  <Button size="icon-xs" variant="ghost" disabled={usada} onClick={() => setEtapas((xs) => xs.filter((_, k) => k !== i))} aria-label="Tirar">
                    <Trash2 />
                  </Button>
                </div>
              </li>
            )
          })}
        </ol>
        <div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => setEtapas((xs) => [...xs, { fase: 'revisao', nome: 'Nova etapa', obrigatoria: false, repetivel: true, conta_revisao: false, fracao_critica: null, nivel_inspecao: null, lqa: null, atividades: [] }])}
          >
            <Plus /> Etapa
          </Button>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={fechar}>
            Cancelar
          </Button>
          <Button onClick={salvar} disabled={ocupado || !nome.trim()}>
            <RotuloEstavel ocupado={ocupado} rotulo="Salvar fluxo" rotuloOcupado="Salvando…" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
