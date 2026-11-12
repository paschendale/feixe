import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Lote, Pessoa, ResultadoAtribuicao } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { dataHora, num } from '@/lib/formato'
import { enviar, useApi } from '@/lib/useApi'

// Equipe da unidade (B5): quem pode receber cargas (conta ativa, lotação da UF, perfil O, V ou S no SGBC), o que cada
// pessoa tem nas mãos, e a troca de responsável no meio (passar as pendentes de uma pessoa para outra).
export default function Equipe() {
  const avisar = useAvisar()
  const { dados, erro } = useApi<{ itens: Pessoa[] }>('/api/equipe', ['carga'])
  const { dados: lotes } = useApi<{ itens: Lote[] }>('/api/lotes', ['lote'])
  const [passar, setPassar] = useState<{ de: string; para: string } | null>(null)

  async function aplicar() {
    if (!passar || !lotes) return
    const abertas = lotes.itens.filter((l) => l.situacao === 'pendente' || l.situacao === 'em_andamento').map((l) => l.id_lote_etapa_atual)
    try {
      const r = await enviar<ResultadoAtribuicao>('/api/cargas/atribuir', { lote_etapas: abertas, de: passar.de, responsavel: passar.para === '-' ? null : passar.para })
      avisar(`${num(r.atribuidas)} cargas passadas.`)
      setPassar(null)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  if (erro) return <p className="text-sm text-destructive">{erro}</p>
  if (!dados) return <p className="text-sm text-muted-foreground">Carregando…</p>
  return (
    <>
      <p className="text-sm text-muted-foreground">
        Quem pode receber cargas na unidade: conta ativa, lotação da UF e perfil de execução (O, V ou S) no SGBC. Perfis se acertam no SGBC.
      </p>
      <Card className="gap-0 overflow-hidden py-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="pl-4">Pessoa</TableHead>
              <TableHead>Perfis</TableHead>
              <TableHead className="text-right">Pendentes</TableHead>
              <TableHead className="text-right">Folhas</TableHead>
              <TableHead>Última conclusão</TableHead>
              <TableHead className="pr-4" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {dados.itens.map((p) => (
              <TableRow key={p.conta}>
                <TableCell className="pl-4 font-medium">
                  {p.nome}
                  <span className="block text-xs font-normal text-muted-foreground">{p.conta}</span>
                </TableCell>
                <TableCell className="max-w-56 truncate text-muted-foreground" title={p.perfis}>
                  {p.perfis}
                </TableCell>
                <TableCell className="tab text-right">{num(p.pendentes)}</TableCell>
                <TableCell className="tab text-right">{num(p.folhas)}</TableCell>
                <TableCell className="text-muted-foreground">{dataHora(p.ultima)}</TableCell>
                <TableCell className="pr-4 text-right">
                  {passar?.de === p.conta ? (
                    <span className="inline-flex items-center gap-2">
                      <Select className="h-8 w-52" value={passar.para} onChange={(e) => setPassar({ ...passar, para: e.target.value })} aria-label="Para quem">
                        <option value="">Para quem?</option>
                        <option value="-">Disponível</option>
                        {dados.itens
                          .filter((x) => x.conta !== p.conta)
                          .map((x) => (
                            <option key={x.conta} value={x.conta}>
                              {x.nome}
                            </option>
                          ))}
                      </Select>
                      <Button size="sm" disabled={!passar.para} onClick={aplicar}>
                        Passar
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setPassar(null)}>
                        Cancelar
                      </Button>
                    </span>
                  ) : (
                    <Button size="sm" variant="ghost" disabled={!p.pendentes} onClick={() => setPassar({ de: p.conta, para: '' })}>
                      Passar pendentes
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </>
  )
}
