import { useState } from 'react'
import { Plus } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import type { Atividade, Catalogo } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { GERACAO, nivelGrade } from '@/lib/formato'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'
import { FormAtividade } from './FormAtividade'

// Catálogo nacional de atividades (B7). Todos veem; só o gerente (CCAR) cria e altera (D-87).
export default function Atividades() {
  const { tem } = useSessao()
  const avisar = useAvisar()
  const gerente = tem('gerente')
  const { dados, erro } = useApi<Catalogo>('/api/catalogo', ['atividade'])
  const [form, setForm] = useState<{ atividade: Atividade | null } | null>(null)

  async function novoTema() {
    const nome = window.prompt('Nome do novo tema')
    if (!nome?.trim()) return
    try {
      await enviar('/api/temas', { nome })
      avisar(`Tema criado: ${nome.trim()}`)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  if (erro) return <p className="text-sm text-destructive">{erro}</p>
  if (!dados) return <p className="text-sm text-muted-foreground">Carregando…</p>

  return (
    <>
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          Catálogo nacional: cada atividade é projeto + tema + fase, com o jeito de gerar as cargas. As GGCs escolhem entre elas ao montar os fluxos.
          {!gerente && ' O cadastro é da CCAR.'}
        </p>
        {gerente && (
          <div className="flex shrink-0 gap-2">
            <Button variant="outline" onClick={novoTema}>
              <Plus /> Novo tema
            </Button>
            <Button onClick={() => setForm({ atividade: null })}>
              <Plus /> Nova atividade
            </Button>
          </div>
        )}
      </div>

      {dados.temas.map((t) => {
        const doTema = dados.atividades.filter((a) => a.id_tema === t.id)
        return (
          <section key={t.id} className="flex flex-col gap-2">
            <h2 className="flex items-center gap-2 text-[15px] font-semibold">
              {t.nome}
              {!t.ativo && <Badge variant="outline">inativo</Badge>}
            </h2>
            <Card className="gap-0 overflow-hidden py-0">
              {doTema.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">Nenhuma atividade.</p>
              ) : (
                <Table className="table-fixed">
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-[38%] pl-4">Atividade</TableHead>
                      <TableHead className="w-[16%]">Fase</TableHead>
                      <TableHead className="w-[14%]">Cargas</TableHead>
                      <TableHead className="w-[7%]">Grade</TableHead>
                      <TableHead className="w-[16%]">Medida</TableHead>
                      <TableHead className="w-[9%] pr-4" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {doTema.map((a) => (
                      <TableRow
                        key={a.id}
                        className={cn(gerente && 'cursor-pointer', !a.ativo && 'text-muted-foreground')}
                        onClick={() => gerente && setForm({ atividade: a })}
                      >
                        <TableCell className="pl-4 font-medium whitespace-normal">{a.nome}</TableCell>
                        <TableCell className="whitespace-normal">{a.fase_nome}</TableCell>
                        <TableCell>{GERACAO[a.geracao ?? ''] ?? '—'}</TableCell>
                        <TableCell className="tab">{nivelGrade(a.grade_nivel)}</TableCell>
                        <TableCell className="whitespace-normal">{a.medida ?? '—'}</TableCell>
                        <TableCell className="pr-4 text-right">
                          {!a.ativo && <Badge variant="outline">inativa</Badge>}
                          {a.ativo && a.em_uso && <Badge variant="secondary">em fluxo</Badge>}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </Card>
          </section>
        )
      })}

      {gerente && <FormAtividade catalogo={dados} atividade={form?.atividade ?? null} aberto={!!form} fechar={() => setForm(null)} />}
    </>
  )
}
