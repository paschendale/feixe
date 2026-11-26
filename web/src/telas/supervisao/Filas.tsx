import { useState } from 'react'
import { ArrowDown, ArrowUp, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { Bloco, Carregando, Colunas, Conteudo, Selo, Tabela, TituloBloco } from '@/components/ds'
import type { Filas as TFilas, ItemFila, Pessoa } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { dataHora, num, plural } from '@/lib/formato'
import { href } from '@/lib/rotas'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { rotuloCurto, usePainel } from '../inicio/ResumoSupervisao'

type Candidata = { id_lote_etapa: number; id_lote: number; rotulo: string; a_atribuir: number }

// Supervisão › Filas (B8, D-106): a fila de folhas de cada pessoa. Quando a pessoa conclui a última carga pendente que
// tem, o Feixe atribui a ela as cargas a atribuir da primeira folha da fila. Ninguém fica com várias folhas abertas e
// ninguém fica parado.
export default function Filas() {
  const avisar = useAvisar()
  const { eu } = useSessao()
  const { painel, lotes } = usePainel()
  const { dados: filas, erro, recarregar } = useApi<TFilas>('/api/filas', ['fila', 'lote', 'carga'])
  const { dados: equipe } = useApi<{ itens: Pessoa[] }>('/api/equipe', ['carga', 'fila'])
  const [ocupado, setOcupado] = useState(false)

  if (!filas || !equipe || !painel.dados || !lotes.dados)
    return (
      <Conteudo>
        <Carregando erro={erro ?? painel.erro ?? lotes.erro} />
      </Conteudo>
    )

  const p = painel.dados
  const aAtribuir = new Map(p.lotes.map((l) => [l.id_lote, l.a_atribuir]))
  const naFila = new Set(filas.itens.map((i) => i.id_lote_etapa))
  const candidatas: Candidata[] = lotes.dados.itens
    .filter((l) => ['pendente', 'em_andamento'].includes(l.situacao ?? '') && l.id_lote_etapa_atual && !naFila.has(l.id_lote_etapa_atual) && (aAtribuir.get(l.id) ?? 0) > 0)
    .map((l) => ({ id_lote_etapa: l.id_lote_etapa_atual!, id_lote: l.id, rotulo: `${l.folha_revisao} · ${l.tema} · ${l.etapa}`, a_atribuir: aAtribuir.get(l.id) ?? 0 }))
  const nomeLote = (id: number) => lotes.dados!.itens.find((l) => l.id === id)?.folha_revisao ?? `#${id}`
  const grupo = (c: string) => p.grupos.find((g) => g.chave === c)
  const doPainel = new Map(p.pessoas.map((x) => [x.conta, x]))
  const filaDe = (conta: string) => filas.itens.filter((i) => i.responsavel === conta).sort((a, b) => a.ordem - b.ordem)
  const pessoas = [...equipe.itens].sort(
    (a, b) => Number(a.pendentes > 0) - Number(b.pendentes > 0) || Number(filaDe(b.conta).length > 0) - Number(filaDe(a.conta).length > 0) || a.nome.localeCompare(b.nome),
  )
  const paradas = pessoas.filter((x) => !x.pendentes && !filaDe(x.conta).length)

  async function rodar(fn: () => Promise<unknown>, ok?: (r: unknown) => string | null) {
    setOcupado(true)
    try {
      const r = await fn()
      const msg = ok?.(r)
      if (msg) avisar(msg)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
      recarregar()
    }
  }

  const adicionar = (pessoa: Pessoa, c: Candidata) =>
    rodar(
      () => enviar<{ atribuida: { folha_revisao: string; atribuidas: number } | null }>('/api/filas', { responsavel: pessoa.conta, id_lote_etapa: c.id_lote_etapa }),
      (r) => {
        const a = (r as { atribuida: { folha_revisao: string; atribuidas: number } | null }).atribuida
        return a
          ? `${pessoa.nome.split(' ')[0]} estava sem carga: a ${a.folha_revisao} já foi atribuída (${num(a.atribuidas)} cargas).`
          : `${c.rotulo.split(' · ')[0]} na fila de ${pessoa.nome.split(' ')[0]}.`
      },
    )
  const mover = (fila: ItemFila[], i: number, d: -1 | 1) => {
    const ids = fila.map((x) => x.id)
    ;[ids[i], ids[i + d]] = [ids[i + d], ids[i]]
    return rodar(() => enviar('/api/filas/ordem', { responsavel: fila[0].responsavel, ids }, 'PUT'))
  }
  const tirar = (item: ItemFila) => rodar(() => enviar(`/api/filas/${item.id}`, undefined, 'DELETE'), () => `${item.folha_revisao} saiu da fila.`)

  return (
    <Conteudo>
      <p className="max-w-[880px] text-lede text-texto-2 [&_b]:font-semibold [&_b]:text-foreground">
        Quando a pessoa conclui a última carga pendente que tem, o Feixe atribui a ela a primeira folha da fila. Ninguém fica com várias folhas abertas e ninguém fica parado.{' '}
        {paradas.length > 0 && (
          <>
            <b className="text-alerta">{plural(paradas.length, 'pessoa está', 'pessoas estão')}</b> sem carga e sem fila; quem está sem carga recebe na hora a folha que você puser na fila.
          </>
        )}
      </p>

      <Tabela fixa largura={900}>
          <Colunas larguras={['26%', '24%', undefined]} />
          <thead>
            <tr>
              <th>Pessoa</th>
              <th>Agora</th>
              <th>Fila (a próxima primeiro)</th>
            </tr>
          </thead>
          <tbody>
            {pessoas.map((x) => {
              const fila = filaDe(x.conta)
              const agora = doPainel.get(x.conta)
              return (
                <tr key={x.conta} className="[&>td]:align-top">
                  <td className="truncate font-medium">
                    {x.nome}
                    {x.conta === eu?.conta ? ' (você)' : ''}
                  </td>
                  <td>
                    {x.pendentes ? (
                      <>
                        {num(x.pendentes)} pendentes
                        {agora && (
                          <span className="block text-nota text-muted-foreground">
                            {agora.grupos.map((c) => (grupo(c) ? rotuloCurto(grupo(c)!) : c)).join(', ')}
                            {agora.lotes.length ? ` · ${agora.lotes.length <= 2 ? agora.lotes.map(nomeLote).join(', ') : plural(agora.lotes.length, 'folha', 'folhas')}` : ''}
                          </span>
                        )}
                      </>
                    ) : (
                      <Selo tom="alerta">sem carga</Selo>
                    )}
                  </td>
                  <td>
                    <ol className="flex flex-col gap-1.5">
                      {fila.map((item, i) => (
                        <li key={item.id} className="flex flex-wrap items-center gap-2">
                          <span className="grid size-5 place-items-center rounded-full bg-primary-suave text-rodape font-semibold text-primary">{i + 1}</span>
                          <a href={href(`supervisao/folhas/${item.id_lote}`, { grupo: 'todas' })} className="tab font-semibold text-primary hover:underline">
                            {item.folha_revisao}
                          </a>
                          <span className="text-nota text-muted-foreground">
                            {item.tema} · {item.etapa}
                          </span>
                          <span className={cn('text-nota', !item.a_atribuir && 'font-semibold text-alerta')}>
                            {item.a_atribuir ? `${num(item.a_atribuir)} a atribuir` : 'nada a atribuir: vai ser pulada'}
                          </span>
                          <span className="ml-auto flex gap-0.5">
                            <Button variant="ghost" size="icon-sm" disabled={ocupado || i === 0} onClick={() => mover(fila, i, -1)} aria-label={`Subir ${item.folha_revisao}`}>
                              <ArrowUp className="size-3.5" />
                            </Button>
                            <Button variant="ghost" size="icon-sm" disabled={ocupado || i === fila.length - 1} onClick={() => mover(fila, i, 1)} aria-label={`Descer ${item.folha_revisao}`}>
                              <ArrowDown className="size-3.5" />
                            </Button>
                            <Button variant="ghost" size="icon-sm" disabled={ocupado} onClick={() => tirar(item)} aria-label={`Tirar ${item.folha_revisao} da fila`}>
                              <X className="size-3.5" />
                            </Button>
                          </span>
                        </li>
                      ))}
                    </ol>
                    <Select
                      className={cn('max-w-[440px] text-nota', fila.length > 0 && 'mt-2')}
                      value=""
                      disabled={ocupado || !candidatas.length}
                      onChange={(e) => {
                        const c = candidatas.find((k) => k.id_lote_etapa === Number(e.target.value))
                        if (c) adicionar(x, c)
                      }}
                      aria-label={`Pôr folha na fila de ${x.nome}`}
                    >
                      <option value="">{candidatas.length ? '+ Pôr uma folha na fila…' : naFila.size ? 'Todas as folhas com cargas a atribuir já estão numa fila' : 'Nenhuma folha com cargas a atribuir'}</option>
                      {candidatas.map((c) => (
                        <option key={c.id_lote_etapa} value={c.id_lote_etapa}>
                          {c.rotulo} · {num(c.a_atribuir)} a atribuir
                        </option>
                      ))}
                    </Select>
                  </td>
                </tr>
              )
            })}
          </tbody>
      </Tabela>

      {filas.recentes.length > 0 && (
        <Bloco className="gap-2">
          <TituloBloco titulo="Atribuídas pela fila nos últimos 7 dias" />
          <ul className="flex flex-col gap-1 text-nota">
            {filas.recentes.map((r) => (
              <li key={r.id}>
                <span className="text-muted-foreground">{dataHora(r.atribuida_em)} · </span>
                <b className="tab">{r.folha_revisao}</b> para {r.nome} ({num(r.atribuidas)} cargas)
              </li>
            ))}
          </ul>
        </Bloco>
      )}
      <p className="text-nota text-muted-foreground">
        Na lista para pôr na fila entram as folhas com etapa aberta e cargas a atribuir que não estão na fila de ninguém. Uma folha da fila que não tem mais nada a atribuir (alguém pegou as cargas) é pulada e fica marcada aqui para você tirar. Desfazer uma conclusão não desfaz a atribuição.
      </p>
    </Conteudo>
  )
}
