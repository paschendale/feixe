import { useEffect, useState } from 'react'
import { Campo, RotuloEstavel } from '@/components/ds'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import type { Atividade, Catalogo } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { GERACAO, nivelGrade } from '@/lib/formato'
import { enviar } from '@/lib/useApi'

type Campos = Pick<Atividade, 'cod_projeto' | 'id_tema' | 'fase' | 'nome' | 'geracao' | 'grade_nivel' | 'id_medidadequalidade' | 'ativo'>

const PRECISAM_GRADE = ['grade', 'amostra_area']

function vazio(c: Catalogo): Campos {
  return {
    cod_projeto: c.projetos.find((p) => p.nome === 'BC100')?.cod_projeto ?? c.projetos[0]?.cod_projeto,
    id_tema: c.temas.find((t) => t.ativo)?.id ?? 0,
    fase: 'aquisicao',
    nome: '',
    geracao: 'grade',
    grade_nivel: 5000,
    id_medidadequalidade: null,
    ativo: true,
  }
}

// Criar ou alterar uma atividade (só gerente). Com cargas ou em fluxo, projeto, tema, fase e medida ficam travados.
export function FormAtividade({ catalogo, atividade, aberto, fechar }: { catalogo: Catalogo; atividade: Atividade | null; aberto: boolean; fechar: () => void }) {
  const avisar = useAvisar()
  const [f, setF] = useState<Campos>(() => vazio(catalogo))
  const [ocupado, setOcupado] = useState(false)
  useEffect(() => {
    if (aberto) setF(atividade ? { ...atividade } : vazio(catalogo))
  }, [aberto, atividade, catalogo])
  const travado = !!atividade && (atividade.em_uso || atividade.tem_cargas)
  const mudar = <K extends keyof Campos>(k: K, v: Campos[K]) => setF((x) => ({ ...x, [k]: v }))
  const cq = f.fase === 'cq'

  async function salvar() {
    setOcupado(true)
    const corpo = { ...f, id_medidadequalidade: cq ? f.id_medidadequalidade : null, grade_nivel: f.grade_nivel || null }
    try {
      const r = atividade ? await enviar<Atividade>(`/api/atividades/${atividade.id}`, corpo, 'PATCH') : await enviar<Atividade>('/api/atividades', corpo)
      avisar(`${atividade ? 'Atividade alterada' : 'Atividade criada'}: ${r.nome}`)
      fechar()
    } catch (e) {
      avisar((e as Error).message, 'erro')
    } finally {
      setOcupado(false)
    }
  }

  return (
    <Dialog open={aberto} onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{atividade ? 'Alterar atividade' : 'Nova atividade'}</DialogTitle>
          <DialogDescription>
            {travado
              ? 'Esta atividade já tem cargas ou está num fluxo: projeto, tema, fase e medida não mudam.'
              : 'Atividade de CQ é tema + medida de qualidade: uma por medida inspecionada.'}
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-4">
          <Campo rotulo="Nome" className="col-span-2">
            <Input value={f.nome} onChange={(e) => mudar('nome', e.target.value)} placeholder="ex.: Aquisição BC100 - LML" />
          </Campo>
          <Campo rotulo="Projeto">
            <Select value={f.cod_projeto} disabled={travado} onChange={(e) => mudar('cod_projeto', Number(e.target.value))}>
              {catalogo.projetos.map((p) => (
                <option key={p.cod_projeto} value={p.cod_projeto}>
                  {p.nome}
                </option>
              ))}
            </Select>
          </Campo>
          <Campo rotulo="Tema">
            <Select value={f.id_tema} disabled={travado} onChange={(e) => mudar('id_tema', Number(e.target.value))}>
              {catalogo.temas
                .filter((t) => t.ativo || t.id === f.id_tema)
                .map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.nome}
                  </option>
                ))}
            </Select>
          </Campo>
          <Campo rotulo="Fase">
            <Select value={f.fase} disabled={travado} onChange={(e) => mudar('fase', e.target.value)}>
              {catalogo.fases.map((x) => (
                <option key={x.codigo} value={x.codigo}>
                  {x.nome}
                </option>
              ))}
            </Select>
          </Campo>
          <Campo rotulo="Medida de qualidade">
            <Select
              value={cq ? (f.id_medidadequalidade ?? '') : ''}
              disabled={!cq || travado}
              onChange={(e) => mudar('id_medidadequalidade', e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">{cq ? 'Escolha a medida' : 'Só em atividade de CQ'}</option>
              {catalogo.elementos_cq
                .filter((m) => m.ativo)
                .map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.nome}
                    {m.nucleo ? '' : ' (local)'}
                  </option>
                ))}
            </Select>
          </Campo>
          <Campo rotulo="Cargas">
            <Select value={f.geracao ?? ''} onChange={(e) => mudar('geracao', e.target.value)}>
              {catalogo.geracoes.map((g) => (
                <option key={g} value={g}>
                  {GERACAO[g] ?? g}
                </option>
              ))}
            </Select>
          </Campo>
          <Campo rotulo="Nível da grade estatística">
            <Select value={f.grade_nivel ?? ''} onChange={(e) => mudar('grade_nivel', e.target.value ? Number(e.target.value) : null)}>
              <option value="">{PRECISAM_GRADE.includes(f.geracao ?? '') ? 'Escolha o nível' : 'Sem grade'}</option>
              {catalogo.niveis_grade.map((n) => (
                <option key={n} value={n}>
                  {nivelGrade(n)}
                </option>
              ))}
            </Select>
          </Campo>
          <label className="col-span-2 flex items-center gap-2">
            <input type="checkbox" checked={f.ativo} onChange={(e) => mudar('ativo', e.target.checked)} /> Ativa (aparece para as GGCs montarem fluxos)
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={fechar}>
            Cancelar
          </Button>
          <Button onClick={salvar} disabled={ocupado || !f.nome.trim()}>
            <RotuloEstavel ocupado={ocupado} rotulo="Salvar" rotuloOcupado="Salvando…" />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
