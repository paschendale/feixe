import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Bloco, Colunas, LinkSeta, RotuloEstavel, Tabela as TabelaDS, TituloBloco, Vazio } from '@/components/ds'
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
    <TabelaDS solta densa fixa largura={820}>
      <Colunas larguras={[150, 160, undefined, 150, 110, cientes ? 130 : 220]} />
      <thead>
        <tr>
          <th>Elemento</th>
          <th>Sua carga</th>
          <th>Anotação</th>
          <th>Avaliador</th>
          <th>{cientes ? 'Ciente em' : 'Registrada'}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {itens.map((o) => (
          <tr key={o.uuid}>
            <td className="truncate font-medium" title={o.elemento ?? undefined}>
              {o.elemento ?? '—'}
            </td>
            <td className="tab truncate font-mono">{o.geocodigo_avaliada ?? (o.id_carga_avaliada ? `nº ${o.id_carga_avaliada}` : '—')}</td>
            <td className="truncate" title={o.anotacao ?? undefined}>
              {o.anotacao ?? <span className="text-muted-foreground">sem anotação</span>}
            </td>
            <td className="truncate text-muted-foreground" title={o.avaliador}>
              {primeiro(o.avaliador)}
            </td>
            <td className="tab truncate text-muted-foreground">{cientes ? `${diaMes(o.ciente_em)} ${hora(o.ciente_em)}` : diaMes(o.criado_em)}</td>
            <td className="py-1.5">
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
    </TabelaDS>
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
        <Bloco>
          <Vazio>Nada para ciência: nenhuma ocorrência nova nas suas cargas.</Vazio>
        </Bloco>
      ) : (
        mostrar.map((itens) => {
          const f = itens[0]
          return (
            <Bloco key={f.id_lote} className="gap-2.5">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="tab text-titulo-3 font-bold">{f.folha_revisao}</span>
                <span className="text-nota text-alerta">
                  {plural(itens.length, 'ocorrência nas suas cargas', 'ocorrências nas suas cargas')}
                  {f.etapa ? ` · ${f.etapa}` : ''}
                </span>
                {itens.length > 1 && (
                  <Button size="sm" variant="outline" className="ml-auto" disabled={acoes.ocupado === `f-${f.id_lote}`} onClick={() => acoes.todas(f.id_lote, f.folha_revisao, itens.length)}>
                    <RotuloEstavel ocupado={acoes.ocupado === `f-${f.id_lote}`} rotulo="Ciente em todas deste lote" rotuloOcupado="Marcando…" />
                  </Button>
                )}
              </div>
              <Tabela itens={itens} acoes={acoes} />
            </Bloco>
          )
        })
      )}
      {limite && folhas.length > mostrar.length && (
        <LinkSeta href="#/execucao/ciencia">
          e mais {plural(folhas.length - mostrar.length, 'lote', 'lotes')} em Execução › Para ciência
        </LinkSeta>
      )}
      {comCientes && dados.cientes.length > 0 && (
        <Bloco className="gap-2.5">
          <TituloBloco titulo="Já com ciência" sub={`últimos ${dados.dias} dias`} />
          <Tabela itens={dados.cientes} acoes={acoes} cientes />
        </Bloco>
      )}
    </div>
  )
}
