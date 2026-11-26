import { useEffect, useState } from 'react'
import { Pie, PieChart } from 'recharts'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'
import { COR, RotuloEstavel } from '@/components/painel'
import type { DecisaoCQ, ItemDecisaoCQ, ResultadoCQ, ResultadoDecisaoCQ, ResultadoPlano } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { lista, num, plural } from '@/lib/formato'
import { enviar } from '@/lib/useApi'
import { comCargas, resumoPreparo } from '../folhas/preparo'

const pc = (x: number) => `${x.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`

// Resultado da passagem de CQ, como o supervisor lê: o rótulo e a cor (com a palavra, nunca só a cor).
export const RESULTADO: Record<ResultadoCQ, { rotulo: string; cor: string; fundo: string }> = {
  aprovado: { rotulo: 'Aprovada', cor: COR.concluida, fundo: '#EEF3FA' },
  reprovado: { rotulo: 'Reprovada', cor: '#8A3B00', fundo: COR.alertaFundo },
  pendente: { rotulo: 'Em avaliação', cor: '#4A5868', fundo: '#F1F3F6' },
  sem_ac: { rotulo: 'Sem Ac no plano', cor: COR.alerta, fundo: COR.alertaFundo },
  sem_planos: { rotulo: 'Sem planos', cor: '#4A5868', fundo: '#F1F3F6' },
}

export function SeloResultado({ resultado }: { resultado: ResultadoCQ }) {
  const r = RESULTADO[resultado]
  return (
    <span className="inline-flex shrink-0 items-center rounded-full px-2.5 py-0.5 text-xs font-semibold" style={{ color: r.cor, background: r.fundo }}>
      {r.rotulo}
    </span>
  )
}

// Velocímetro do nível de conformidade (D-62): meia-lua de 0 ao fim da escala, com a faixa até a fração crítica
// (dentro) e a de cima (acima), e o arco do percentual observado por dentro. A leitura em texto vem ao lado; o desenho
// é decorativo para o leitor de tela (a leitura é o rótulo).
export function Velocimetro({ observado, fracao, tamanho = 112 }: { observado: number | null; fracao: number | null; tamanho?: number }) {
  const fc = fracao ?? null
  const escala = Math.min(100, Math.max(fc != null ? fc * 2 : 10, (observado ?? 0) * 1.25, 1))
  const faixas =
    fc != null
      ? [
          { nome: 'dentro', valor: fc, fill: '#DCE6F2' },
          { nome: 'acima', valor: Math.max(escala - fc, 0), fill: '#F6DDB8' },
        ]
      : [{ nome: 'escala', valor: escala, fill: COR.vazio }]
  const v = Math.min(observado ?? 0, escala)
  const acima = fc != null && observado != null && observado > fc
  const arco = [
    { nome: 'observado', valor: v, fill: acima ? COR.naoConforme : COR.concluida },
    { nome: 'resto', valor: escala - v, fill: 'transparent' },
  ]
  const alto = tamanho / 2 + 6
  const r = tamanho / 2 - 2
  return (
    <div aria-hidden className="relative shrink-0" style={{ width: tamanho, height: alto }}>
      <PieChart width={tamanho} height={alto} margin={{ top: 0, right: 0, bottom: 0, left: 0 }}>
        <Pie data={faixas} dataKey="valor" cx="50%" cy={tamanho / 2} startAngle={180} endAngle={0} innerRadius={r - 7} outerRadius={r} stroke="#fff" strokeWidth={2} isAnimationActive={false} />
        <Pie data={arco} dataKey="valor" cx="50%" cy={tamanho / 2} startAngle={180} endAngle={0} innerRadius={r - 19} outerRadius={r - 10} stroke="none" cornerRadius={4} isAnimationActive={false} />
      </PieChart>
      <span className="tab absolute inset-x-0 bottom-0 text-center text-[15px] leading-none font-semibold">{observado == null ? '—' : pc(observado)}</span>
    </div>
  )
}

// Um elemento do resultado: o velocímetro e, ao lado, a frase do plano e a leitura do nível de conformidade.
export function ElementoCQ({ p, compacto = false }: { p: ResultadoPlano; compacto?: boolean }) {
  const c = p.conformidade
  return (
    <div className="flex items-center gap-3" role="group" aria-label={c.leitura}>
      <Velocimetro observado={c.observado} fracao={c.fracao_critica} tamanho={compacto ? 88 : 112} />
      <div className="flex min-w-0 flex-col gap-0.5 text-[13px]">
        <span className="font-medium" style={{ color: p.excede ? COR.alerta : undefined }}>
          {p.frase}
        </span>
        <span className="text-muted-foreground">
          {c.observado == null
            ? 'nenhuma amostra avaliada ainda'
            : `${pc(c.observado)} de não conformes nas ${num(p.avaliadas)} avaliadas · fração crítica ${c.fracao_critica == null ? 'não gravada no plano' : pc(c.fracao_critica)}${c.situacao === 'acima' ? ' · acima' : c.situacao === 'dentro' ? ' · dentro' : ''}`}
        </span>
      </div>
    </div>
  )
}

const folhas = (xs: ItemDecisaoCQ[]) => (xs.length <= 8 ? lista(xs.map((i) => i.folha_revisao)) : `${lista(xs.slice(0, 6).map((i) => i.folha_revisao))} e mais ${num(xs.length - 6)}`)

// Aprovar ou Nova revisão no CQ (D4), em uma ou várias folhas, com prévia, observação obrigatória e o aviso explícito
// quando se aprova uma folha reprovada. Aprovar conclui o CQ e abre a etapa seguinte; Nova revisão conclui o CQ como
// reprovada e abre a revisão seguinte (folha-N+1), às cegas ou com as correções a fazer (D-66). Depois, o Distribuir.
export function DecidirCQ({
  lotes,
  decisao,
  observacao = '',
  fechar,
}: {
  lotes: number[]
  decisao: DecisaoCQ | null
  observacao?: string
  fechar: (abertas?: number[]) => void
}) {
  const avisar = useAvisar()
  const [itens, setItens] = useState<ItemDecisaoCQ[] | null>(null)
  const [obs, setObs] = useState('')
  const [forcar, setForcar] = useState(false)
  const [expor, setExpor] = useState(false)
  const [ocupado, setOcupado] = useState(false)
  const aberto = lotes.length > 0 && decisao !== null

  useEffect(() => {
    if (!aberto) return
    setItens(null)
    setObs(observacao)
    setForcar(false)
    setExpor(false)
    enviar<{ itens: ItemDecisaoCQ[] }>('/api/lotes/cq_decisao', { lotes, decisao, previa: true })
      .then((r) => setItens(r.itens))
      .catch((e) => avisar((e as Error).message, 'erro'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lotes, decisao])

  const validos = (itens ?? []).filter((i) => !i.erro)
  const recusados = (itens ?? []).filter((i) => i.erro)
  const reprovadas = validos.filter((i) => i.resultado === 'reprovado')
  const aprovar = decisao === 'aprovar'
  const pedeConfirmacao = aprovar && reprovadas.length > 0
  const destino = [...new Set(validos.map((i) => i.proxima).filter((x): x is string => !!x))]

  async function confirmar() {
    setOcupado(true)
    try {
      const r = await enviar<ResultadoDecisaoCQ>('/api/lotes/cq_decisao', { lotes: validos.map((i) => i.id_lote), decisao, observacao: obs, previa: false, forcar, expor_ocorrencias: expor })
      const feito = aprovar ? 'aprovada' : 'com nova revisão'
      const etapas = lista([...new Set(r.abertas.map((a) => a.etapa))])
      avisar([r.decididas.length && `${plural(r.decididas.length, `folha ${feito}`, `folhas ${aprovar ? 'aprovadas' : 'com nova revisão'}`)} no CQ.`, r.abertas.length && `${etapas} aberta.`, resumoPreparo(r.preparo)].filter(Boolean).join(' '))
      r.erros.forEach((e) => avisar(e.erro, 'erro'))
      const prontas = comCargas(r.preparo)
      fechar(r.abertas.filter((a) => prontas.has(a.id_lote_etapa)).map((a) => a.id_lote))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  const rotulo = aprovar ? `Aprovar ${plural(validos.length, 'folha', 'folhas')}` : `Abrir nova revisão em ${plural(validos.length, 'folha', 'folhas')}`
  return (
    <Dialog open={aberto} onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{aprovar ? 'Aprovar no CQ' : 'Nova revisão'}</DialogTitle>
          <DialogDescription>
            {aprovar
              ? `Conclui o CQ como aprovada${destino.length ? ` e abre ${lista(destino)}` : ''}. As cargas da etapa nova saem na hora, e a distribuição abre em seguida.`
              : `Conclui o CQ como reprovada e abre ${destino.length ? lista(destino) : 'a revisão'} na revisão seguinte, com as cargas pela grade. A distribuição sugere outra pessoa que não quem fez a revisão avaliada.`}
          </DialogDescription>
        </DialogHeader>
        {!itens && <div className="grid min-h-[200px] place-items-center rounded-lg border text-sm text-muted-foreground">Conferindo as folhas…</div>}
        {itens && (
          <div className="flex max-h-[50vh] min-h-[200px] flex-col gap-2.5 overflow-auto">
            {validos.map((i) => (
              <div key={i.id_lote} className="flex flex-col gap-1 rounded-lg border bg-[#F7F9FB] px-4 py-3">
                <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                  <b className="tab">{i.folha_revisao}</b>
                  <SeloResultado resultado={i.resultado} />
                  <span className="ml-auto text-[13px]">
                    {aprovar ? (
                      i.proxima ? (
                        <>
                          abre <b className="text-ibge">{i.proxima}</b>
                        </>
                      ) : (
                        'última etapa do fluxo: só conclui'
                      )
                    ) : (
                      <>
                        abre <b className="text-ibge">{i.proxima}</b> como <b className="tab">{i.nova_folha}</b>
                      </>
                    )}
                  </span>
                </div>
                {i.frase && <span className="text-[13px] text-texto-2">{i.frase}</span>}
                {!aprovar && i.autores.length > 0 && <span className="text-xs text-muted-foreground">Revisão avaliada feita por {lista(i.autores)}: a sugestão do Distribuir será outra pessoa.</span>}
                {i.aviso && (
                  <span className="text-xs" style={{ color: COR.alerta }}>
                    {i.aviso}
                  </span>
                )}
              </div>
            ))}
            {recusados.length > 0 && (
              <div className="text-[13px]">
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
        {/* Enquanto confere, o campo já está lá: o diálogo não cresce quando a prévia chega. */}
        {(!itens || validos.length > 0) && (
          <div className="flex flex-col gap-2.5">
            {pedeConfirmacao && (
              <label className="flex items-start gap-2 rounded-lg px-3.5 py-2.5 text-[13px]" style={{ background: COR.alertaFundo, color: '#5C3D00' }}>
                <input type="checkbox" className="mt-0.5" checked={forcar} onChange={(e) => setForcar(e.target.checked)} />
                <span>
                  <b>Aprovar mesmo reprovada{reprovadas.length > 1 ? 's' : ''} no CQ</b> ({folhas(reprovadas)}): os não conformes passaram do aceito. A decisão é sua e fica no histórico com o resultado e a sua observação.
                </span>
              </label>
            )}
            {!aprovar && (
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" className="mt-1" checked={expor} onChange={(e) => setExpor(e.target.checked)} />
                <span>
                  Incluir as correções a serem feitas
                  <span className="block text-xs text-muted-foreground">Mostra a quem fizer a revisão as ocorrências do CQ. Sem isso, a revisão é às cegas.</span>
                </span>
              </label>
            )}
            <label className="flex flex-col gap-1.5 text-[13px] text-texto-2">
              Observação (obrigatória, vai para o histórico de cada folha com o resultado por elemento)
              <Textarea rows={2} value={obs} onChange={(e) => setObs(e.target.value)} placeholder={aprovar ? 'Ex.: dentro do aceito, segue para a correção de inspeção' : 'Ex.: comissão acima do aceito, revisar a folha toda'} className="text-sm text-foreground" />
            </label>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => fechar()}>
            Cancelar
          </Button>
          <Button className="font-semibold" disabled={!validos.length || !obs.trim() || ocupado || (pedeConfirmacao && !forcar)} onClick={confirmar}>
            <RotuloEstavel ocupado={ocupado} rotulo={rotulo} rotuloOcupado="Gravando…" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
