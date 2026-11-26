import { useMemo, useState } from 'react'
import { MousePointerSquareDashed } from 'lucide-react'
import { Bloco, Campo, Nota, RotuloEstavel } from '@/components/ds'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import type { ResultadoCriacao } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { lista, num, plural } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { enviar } from '@/lib/useApi'
import { EscolherFluxo } from './EscolherFluxo'
import { criadosComCargas, resumoCriacao } from './NovaFolha'

type Selecao = {
  camada: string
  feicoes: number
  wkt: string
  campos: string[]
  campo_nome: string
  itens: { wkt: string; atributos: Record<string, string> }[]
}

const MOSTRAR = 8

// Lote livre (B3): polígonos ad hoc (bacia, município, área desenhada) vindos da seleção da camada ativa no QGIS. Com
// várias feições selecionadas, o padrão é um lote por feição (D-154), com o nome tirado de um campo da camada (o Feixe
// sugere o campo de nome ou de código); a opção de unir tudo num lote só continua.
export function NovoLoteLivre({ aberto, fechar }: { aberto: boolean; fechar: (criados?: number[]) => void }) {
  const avisar = useAvisar()
  const { conectado } = useSessao()
  const [fluxo, setFluxo] = useState<number | null>(null)
  const [nome, setNome] = useState('')
  const [selecao, setSelecao] = useState<Selecao | null>(null)
  const [porFeicao, setPorFeicao] = useState(true)
  const [campo, setCampo] = useState('')
  const [prefixo, setPrefixo] = useState('')
  const [ocupado, setOcupado] = useState(false)

  async function lerSelecao() {
    try {
      const s = await enviar<Selecao>('/api/qgis/selecao')
      setSelecao(s)
      setPorFeicao(s.feicoes > 1)
      setCampo(s.campo_nome)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  // O nome de cada lote: prefixo + valor do campo; vazio fica sem nome (o servidor recusa só esse).
  const nomes = useMemo(() => (selecao?.itens ?? []).map((i) => (i.atributos[campo] ? `${prefixo}${i.atributos[campo]}`.trim() : '')), [selecao, campo, prefixo])
  const vazios = nomes.filter((n) => !n).length
  const repetidos = nomes.length - new Set(nomes.filter(Boolean)).size - vazios
  const varios = porFeicao && (selecao?.feicoes ?? 0) > 1

  async function criar() {
    setOcupado(true)
    try {
      const corpo = varios ? { tipo: 'livre', id_fluxo: fluxo, lotes: selecao!.itens.map((i, k) => ({ nome: nomes[k], wkt: i.wkt })) } : { tipo: 'livre', id_fluxo: fluxo, nome, wkt: selecao?.wkt }
      const r = await enviar<ResultadoCriacao & { erros?: { nome: string; erro: string }[] }>('/api/lotes', corpo)
      avisar(resumoCriacao(r), r.preparo?.erro ? 'erro' : undefined)
      if (r.erros?.length) avisar(`Ficaram de fora: ${r.erros.map((e) => `${e.nome} (${e.erro})`).join('; ')}.`, 'erro')
      setNome('')
      setSelecao(null)
      fechar(criadosComCargas(r))
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  const pronto = !!fluxo && !!selecao && (varios ? nomes.some(Boolean) : !!nome.trim())
  return (
    <Dialog open={aberto} onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Novo lote livre</DialogTitle>
          <DialogDescription>Para unidades que não são folha (bacia, município). Selecione no QGIS as feições, na camada ativa: com várias, cada feição vira um lote.</DialogDescription>
        </DialogHeader>
        <EscolherFluxo valor={fluxo} mudar={(f) => setFluxo(f?.id ?? null)} />
        <div className="flex items-center gap-3">
          <Button variant="tinted" onClick={lerSelecao} disabled={!conectado}>
            <MousePointerSquareDashed /> Usar a seleção do QGIS
          </Button>
          <span className="text-muted-foreground">{selecao ? `${plural(selecao.feicoes, 'feição', 'feições')} de ${selecao.camada}` : 'Nenhum polígono ainda.'}</span>
        </div>

        {selecao && selecao.feicoes > 1 && (
          <Campo rotulo="Como criar" grupo>
            <label className="flex items-center gap-2 font-normal text-foreground">
              <input type="radio" checked={porFeicao} onChange={() => setPorFeicao(true)} /> Um lote por feição ({plural(selecao.feicoes, 'lote', 'lotes')})
            </label>
            <label className="flex items-center gap-2 font-normal text-foreground">
              <input type="radio" checked={!porFeicao} onChange={() => setPorFeicao(false)} /> Um lote só, unindo as {num(selecao.feicoes)} feições
            </label>
          </Campo>
        )}

        {varios ? (
          <>
            <div className="flex flex-wrap gap-3">
              <Campo rotulo="Nome do lote vem do campo" className="min-w-[200px] flex-1">
                <Select value={campo} onChange={(e) => setCampo(e.target.value)}>
                  {selecao!.campos.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </Select>
              </Campo>
              <Campo rotulo="Prefixo (opcional)" className="w-[200px]">
                <Input placeholder="ex.: Ottobacia " value={prefixo} onChange={(e) => setPrefixo(e.target.value)} />
              </Campo>
            </div>
            <Bloco poco className="gap-1.5">
              <span className="text-nota text-muted-foreground">Os lotes vão se chamar:</span>
              <span className="text-nota">
                {lista(nomes.filter(Boolean).slice(0, MOSTRAR))}
                {nomes.filter(Boolean).length > MOSTRAR && ` e mais ${num(nomes.filter(Boolean).length - MOSTRAR)}`}
              </span>
            </Bloco>
            {(vazios > 0 || repetidos > 0) && (
              <Nota tom="alerta">
                {[vazios && `${plural(vazios, 'feição está', 'feições estão')} com o campo vazio`, repetidos && `${plural(repetidos, 'nome se repete', 'nomes se repetem')}`].filter(Boolean).join(' e ')}: {vazios + repetidos === 1 ? 'essa fica' : 'essas ficam'} de fora. Escolha um campo com um valor diferente em cada feição (um código, por exemplo).
              </Nota>
            )}
          </>
        ) : (
          <Campo rotulo="Nome">
            <Input placeholder="ex.: Bacia do Paranoá" value={nome} onChange={(e) => setNome(e.target.value)} />
          </Campo>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => fechar()}>
            Cancelar
          </Button>
          <Button onClick={criar} disabled={!pronto || ocupado}>
            <RotuloEstavel ocupado={ocupado} rotulo={varios ? `Criar ${plural(new Set(nomes.filter(Boolean)).size, 'lote', 'lotes')} e gerar as cargas` : 'Criar o lote e gerar as cargas'} rotuloOcupado="Criando e gerando as cargas…" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
