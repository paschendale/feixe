import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import type { Catalogo, FluxoCompleto } from '@/lib/api'
import { useAvisar } from '@/lib/avisos'
import { useSessao } from '@/lib/sessao'
import { enviar, useApi } from '@/lib/useApi'

// Novo fluxo: do modelo da CCAR (o caminho do DF, D-65) ou copiado de outra unidade, e depois ajustado.
export function NovoFluxo({ catalogo, aberto, fechar }: { catalogo: Catalogo; aberto: boolean; fechar: (f?: FluxoCompleto) => void }) {
  const avisar = useAvisar()
  const { eu } = useSessao()
  const [modo, setModo] = useState<'modelo' | 'copia'>('modelo')
  const projetos = (eu?.perfis ?? []).filter((p) => p.papel === 'supervisor')
  const [projeto, setProjeto] = useState<number | null>(null)
  const [tema, setTema] = useState<number | null>(null)
  const [origem, setOrigem] = useState<number | null>(null)
  const [nome, setNome] = useState('')
  const { dados: outros } = useApi<{ itens: FluxoCompleto[] }>(aberto && modo === 'copia' ? '/api/fluxos/completos?outras=1' : null)
  const proj = projeto ?? projetos[0]?.cod_projeto ?? null

  async function criar() {
    try {
      const corpo = modo === 'modelo' ? { modo, nome, cod_projeto: proj, id_tema: tema } : { modo, nome, id_origem: origem }
      const f = await enviar<FluxoCompleto>('/api/fluxos', corpo)
      avisar(`Fluxo criado: ${f.nome}. Confira as etapas e as atividades.`)
      fechar(f)
    } catch (e) {
      avisar((e as Error).message, 'erro')
    }
  }

  return (
    <Dialog open={aberto} onOpenChange={(v) => !v && fechar()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Novo fluxo</DialogTitle>
          <DialogDescription>Comece pelo modelo da CCAR ou copie o fluxo de outra unidade; depois ajuste as etapas.</DialogDescription>
        </DialogHeader>
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={modo === 'modelo'} onChange={() => setModo('modelo')} /> Modelo da CCAR
          </label>
          <label className="flex items-center gap-1.5">
            <input type="radio" checked={modo === 'copia'} onChange={() => setModo('copia')} /> Copiar de outra unidade
          </label>
        </div>
        {modo === 'modelo' ? (
          <div className="grid grid-cols-2 gap-3">
            <div className="grid gap-1.5">
              <Label htmlFor="nf-projeto">Projeto</Label>
              <Select id="nf-projeto" value={proj ?? ''} onChange={(e) => setProjeto(Number(e.target.value))}>
                {projetos.map((p) => (
                  <option key={p.cod_projeto} value={p.cod_projeto}>
                    {p.projeto}
                  </option>
                ))}
              </Select>
            </div>
            <div className="grid gap-1.5">
              <Label htmlFor="nf-tema">Tema</Label>
              <Select id="nf-tema" value={tema ?? ''} onChange={(e) => setTema(Number(e.target.value) || null)}>
                <option value="">Escolha</option>
                {catalogo.temas
                  .filter((t) => t.ativo)
                  .map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.nome}
                    </option>
                  ))}
              </Select>
            </div>
          </div>
        ) : (
          <div className="grid gap-1.5">
            <Label htmlFor="nf-origem">Fluxo de origem</Label>
            <Select id="nf-origem" value={origem ?? ''} onChange={(e) => setOrigem(Number(e.target.value) || null)}>
              <option value="">Escolha</option>
              {outros?.itens.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.uf} · {f.projeto} · {f.tema} · {f.nome}
                </option>
              ))}
            </Select>
          </div>
        )}
        <div className="grid gap-1.5">
          <Label htmlFor="nf-nome">Nome</Label>
          <Input id="nf-nome" value={nome} onChange={(e) => setNome(e.target.value)} placeholder="ex.: DF LML" />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => fechar()}>
            Cancelar
          </Button>
          <Button onClick={criar} disabled={!nome.trim() || (modo === 'modelo' ? !proj || !tema : !origem)}>
            Criar fluxo
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
