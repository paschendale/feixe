import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Bloco, COR, Colunas, LinkSeta, RotuloEstavel } from '@/components/painel'
import type { OcorrenciaCiencia, ParaCiencia as Dados } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { diaMes, hora, plural } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { enviar } from '@/lib/useApi'

const primeiro = (n: string) => n.split(' ').slice(0, 2).join(' ')

// As ocorrências agrupadas pela folha (id_lote), na ordem em que chegam.
function porFolha(itens: OcorrenciaCiencia[]) {
  const m = new Map<number, OcorrenciaCiencia[]>()
  for (const o of itens) m.set(o.id_lote, [...(m.get(o.id_lote) ?? []), o])
  return [...m.values()]
}

function useCiencia() {
  const avisar = useAvisar()
  const [ocupado, setOcupado] = useState<string | null>(null)
  async function rodar(chave: string, fn: () => Promise<unknown>, ok: string) {
    setOcupado(chave)
    try {
      await fn()
      avisar(ok)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(null)
    }
  }
  return {
    ocupado,
    ver: (o: OcorrenciaCiencia) => rodar(o.uuid, () => enviar(`/api/inspecoes/${o.uuid}/zoom`), 'Ocorrência no mapa do QGIS.'),
    ciente: (o: OcorrenciaCiencia) => rodar(o.uuid, () => enviar(`/api/inspecoes/${o.uuid}/ciente`), `Ciente: ${o.elemento ?? 'ocorrência'} em ${o.folha_revisao}.`),
    todas: (id_lote: number, folha: string, n: number) => rodar(`f-${id_lote}`, () => enviar('/api/inspecoes/ciente', { id_lote }), `Ciente em ${plural(n, 'ocorrência', 'ocorrências')} de ${folha}.`),
  }
}

function Tabela({ itens, acoes, cientes }: { itens: OcorrenciaCiencia[]; acoes: ReturnType<typeof useCiencia>; cientes?: boolean }) {
  const { conectado } = useSessao()
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] table-fixed border-collapse text-[13px]">
        <Colunas larguras={[150, 160, undefined, 150, 110, cientes ? 130 : 220]} />
        <thead>
          <tr className="text-left text-xs text-muted-foreground">
            <th className="border-b py-2 pr-2 font-medium">Elemento</th>
            <th className="border-b px-2 py-2 font-medium">Sua carga</th>
            <th className="border-b px-2 py-2 font-medium">Anotação</th>
            <th className="border-b px-2 py-2 font-medium">Avaliador</th>
            <th className="border-b px-2 py-2 font-medium">{cientes ? 'Ciente em' : 'Registrada'}</th>
            <th className="border-b py-2 pl-2" />
          </tr>
        </thead>
        <tbody>
          {itens.map((o) => (
            <tr key={o.uuid} className="border-b border-linha last:border-0">
              <td className="truncate py-2 pr-2 font-medium" title={o.elemento ?? undefined}>
                {o.elemento ?? '—'}
              </td>
              <td className="tab truncate px-2 py-2 font-mono">{o.geocodigo_avaliada ?? (o.id_carga_avaliada ? `nº ${o.id_carga_avaliada}` : '—')}</td>
              <td className="truncate px-2 py-2" title={o.anotacao ?? undefined}>
                {o.anotacao ?? <span className="text-muted-foreground">sem anotação</span>}
              </td>
              <td className="truncate px-2 py-2 text-muted-foreground" title={o.avaliador}>
                {primeiro(o.avaliador)}
              </td>
              <td className="tab truncate px-2 py-2 text-muted-foreground">{cientes ? `${diaMes(o.ciente_em)} ${hora(o.ciente_em)}` : diaMes(o.criado_em)}</td>
              <td className="py-1.5 pl-2">
                <span className="flex justify-end gap-1.5">
                  <Button size="sm" variant="outline" disabled={!conectado || acoes.ocupado === o.uuid} onClick={() => acoes.ver(o)}>
                    Ver no QGIS
                  </Button>
                  {!cientes && (
                    <Button size="sm" className="w-[76px]" disabled={acoes.ocupado === o.uuid || !o.pode_ciente} onClick={() => acoes.ciente(o)}>
                      Ciente
                    </Button>
                  )}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// Para ciência (D-66): as ocorrências que o avaliador apontou nas cargas da pessoa. Ciência é retorno, não correção: a
// correção vem na correção de inspeção ou na revisão de outra pessoa. No Início, `limite` mostra só as primeiras folhas.
export function ParaCiencia({ dados, limite, comCientes }: { dados: Dados; limite?: number; comCientes?: boolean }) {
  const acoes = useCiencia()
  const folhas = porFolha(dados.pendentes)
  const mostrar = limite ? folhas.slice(0, limite) : folhas
  return (
    <div className="flex flex-col gap-4">
      {folhas.length === 0 ? (
        <Bloco className="text-muted-foreground">Nada para ciência: nenhuma ocorrência nova nas suas cargas.</Bloco>
      ) : (
        mostrar.map((itens) => {
          const f = itens[0]
          return (
            <Bloco key={f.id_lote} className="gap-2.5 border-[#F0D9B5]" style={{ background: '#FFFBF4' }}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="tab text-base font-bold">{f.folha_revisao}</span>
                <span className="text-[13px]" style={{ color: COR.alerta }}>
                  {plural(itens.length, 'ocorrência nas suas cargas', 'ocorrências nas suas cargas')}
                  {f.etapa ? ` · ${f.etapa}` : ''}
                </span>
                {itens.length > 1 && (
                  <Button size="sm" variant="outline" className="ml-auto" disabled={acoes.ocupado === `f-${f.id_lote}`} onClick={() => acoes.todas(f.id_lote, f.folha_revisao, itens.length)}>
                    <RotuloEstavel ocupado={acoes.ocupado === `f-${f.id_lote}`} rotulo="Ciente em todas desta folha" rotuloOcupado="Marcando…" />
                  </Button>
                )}
              </div>
              <Tabela itens={itens} acoes={acoes} />
            </Bloco>
          )
        })
      )}
      {limite && folhas.length > mostrar.length && (
        <LinkSeta href="#/execucao/ciencia" className="text-sm">
          e mais {plural(folhas.length - mostrar.length, 'folha', 'folhas')} em Execução › Para ciência
        </LinkSeta>
      )}
      {comCientes && dados.cientes.length > 0 && (
        <Bloco className="gap-2.5">
          <div className="flex flex-wrap items-baseline gap-x-2.5">
            <h2 className="font-semibold">Já com ciência</h2>
            <span className="text-[13px] text-muted-foreground">últimos {dados.dias} dias</span>
          </div>
          <Tabela itens={dados.cientes} acoes={acoes} cientes />
        </Bloco>
      )}
    </div>
  )
}
