import { useState } from 'react'
import { Campo, Segmentado } from '@/components/ds'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
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
        <Segmentado
          rotulo="Origem do fluxo"
          ativa={modo}
          escolher={setModo}
          opcoes={[
            { id: 'modelo', rotulo: 'Modelo da CCAR' },
            { id: 'copia', rotulo: 'Copiar de outra unidade' },
          ]}
        />
        {modo === 'modelo' ? (
          <div className="grid grid-cols-2 gap-3">
            <Campo rotulo="Projeto">
              <Select value={proj ?? ''} onChange={(e) => setProjeto(Number(e.target.value))}>
                {projetos.map((p) => (
                  <option key={p.cod_projeto} value={p.cod_projeto}>
                    {p.projeto}
                  </option>
                ))}
              </Select>
            </Campo>
            <Campo rotulo="Tema">
              <Select value={tema ?? ''} onChange={(e) => setTema(Number(e.target.value) || null)}>
                <option value="">Escolha</option>
                {catalogo.temas
                  .filter((t) => t.ativo)
                  .map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.nome}
                    </option>
                  ))}
              </Select>
            </Campo>
          </div>
        ) : (
          <Campo rotulo="Fluxo de origem">
            <Select value={origem ?? ''} onChange={(e) => setOrigem(Number(e.target.value) || null)}>
              <option value="">Escolha</option>
              {outros?.itens.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.uf} · {f.projeto} · {f.tema} · {f.nome}
                </option>
              ))}
            </Select>
          </Campo>
        )}
        <Campo rotulo="Nome">
          <Input value={nome} onChange={(e) => setNome(e.target.value)} placeholder="ex.: DF LML" />
        </Campo>
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
