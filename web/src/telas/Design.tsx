import { useState } from 'react'
import { Play } from 'lucide-react'
import { Anel, Barra, BarrasDia, Bloco, COR, Campo, Colunas, Conteudo, Fichas, Legenda, LinhaLista, LinkSeta, Lista, Metrica, Nota, Ponto, Rotulo, Segmentado, Selo, Tabela, TituloBloco, Vazio } from '@/components/ds'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { STATUS, Status } from '@/lib/status'

// Vitrine do design system (#/design, fora do menu): cada peça com o uso certo. É a referência para telas novas.
function Exemplo({ titulo, uso, children }: { titulo: string; uso: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-col gap-0.5">
        <h2 className="text-titulo-2 font-semibold">{titulo}</h2>
        <p className="max-w-[760px] text-nota text-muted-foreground">{uso}</p>
      </div>
      {children}
    </section>
  )
}

const DIAS = Array.from({ length: 10 }, (_, i) => ({ dia: String(i), rotulo: `${17 + i}/11`, n: [0, 2, 5, 0, 8, 6, 0, 3, 9, 4][i] }))

export default function Design() {
  const [seg, setSeg] = useState<'todas' | 'producao' | 'cq'>('todas')
  const [ficha, setFicha] = useState('a')
  return (
    <Conteudo largura={1100} className="gap-12">
      <div className="flex flex-col gap-1">
        <Rotulo className="px-0">Feixe</Rotulo>
        <h1 className="text-titulo-grande font-bold">Design system</h1>
        <p className="max-w-[760px] text-lede text-texto-2">
          Superfícies brancas sobre fundo cinza, sem bordas; um único azul de ação; estados sempre em par texto e fundo suave. Tokens em <code>src/index.css</code>, peças em <code>src/components/ds</code> e <code>components/ui</code>.
        </p>
      </div>

      <Exemplo titulo="Texto" uso="Use a escala, nunca text-[Npx]. Títulos em bold/semibold; o resto em regular, com o secundário em muted-foreground.">
        <Bloco className="gap-2">
          <span className="text-titulo-grande font-bold">Título grande · cabeçalho de módulo</span>
          <span className="text-titulo-1 font-bold">Título 1 · seção do Início</span>
          <span className="text-titulo-2 font-semibold">Título 2 · diálogo, bloco importante</span>
          <span className="text-titulo-3 font-semibold">Título 3 · título de bloco</span>
          <span className="text-lede text-texto-2">Lede · a frase-resumo do topo da tela</span>
          <span className="text-corpo">Corpo · texto padrão, tabelas</span>
          <span className="text-nota text-muted-foreground">Nota · descrições, subtítulos, detalhes</span>
          <span className="text-rodape text-muted-foreground">Rodapé · cabeçalho de tabela, legendas de campo</span>
          <span className="text-legenda text-muted-foreground">Legenda · eixos, marcas de gráfico</span>
          <span className="tab text-numero font-bold text-primary">1.205</span>
        </Bloco>
      </Exemplo>

      <Exemplo titulo="Cores" uso="Estados: neutro, info, sucesso, alerta, perigo — sempre o texto e o fundo do mesmo tom. Dados: a escala do azul-aço ao azul IBGE.">
        <div className="flex flex-wrap gap-2">
          {(['neutro', 'info', 'sucesso', 'alerta', 'perigo'] as const).map((t) => (
            <Selo key={t} tom={t}>
              {t}
            </Selo>
          ))}
        </div>
        <div className="flex flex-wrap gap-4">
          {Object.entries(STATUS).map(([k]) => (
            <Status key={k} s={k as keyof typeof STATUS} />
          ))}
        </div>
      </Exemplo>

      <Exemplo titulo="Botões" uso="Uma ação primária por área. Tinted para a ação secundária em destaque; outline (bordered) para as neutras; ghost dentro de linhas e tabelas; link para navegar no meio do texto.">
        <Bloco className="flex-row flex-wrap items-center gap-2.5">
          <Button>
            <Play className="size-3.5 fill-current" /> Continuar no QGIS
          </Button>
          <Button variant="tinted">Distribuir</Button>
          <Button variant="outline">Ver as cargas</Button>
          <Button variant="secondary">Cancelar</Button>
          <Button variant="ghost">Limpar</Button>
          <Button variant="destructive-tinted">Desfazer</Button>
          <Button variant="destructive">Excluir</Button>
          <Button variant="link">Abrir o lote</Button>
          <Button variant="tinted" size="icon" className="rounded-full" aria-label="Continuar no QGIS">
            <Play className="size-3.5 fill-current" />
          </Button>
          <Button size="sm" variant="outline">
            Pequeno
          </Button>
          <Button size="lg">Grande</Button>
        </Bloco>
      </Exemplo>

      <Exemplo titulo="Campos e filtros" uso="Campo rotula um controle; Segmentado para 2 a 6 escolhas exclusivas; Fichas para muitas escolhas com contagem (atividades).">
        <Bloco className="gap-5">
          <div className="flex flex-wrap items-end gap-3">
            <Campo rotulo="Buscar lote">
              <Input type="search" placeholder="MI ou nome" className="w-56" />
            </Campo>
            <Campo rotulo="Situação">
              <Select className="w-48">
                <option>Todas</option>
              </Select>
            </Campo>
          </div>
          <Segmentado
            rotulo="Tipo"
            ativa={seg}
            escolher={setSeg}
            opcoes={[
              { id: 'todas', rotulo: 'Todas', contagem: 14 },
              { id: 'producao', rotulo: 'Produção', contagem: 3 },
              { id: 'cq', rotulo: 'CQ', contagem: 11 },
            ]}
          />
          <Fichas
            rotulo="Atividade"
            ativa={ficha}
            escolher={setFicha}
            fichas={[
              { id: 'a', rotulo: 'Aquisição BC100 - LML', contagem: 7 },
              { id: 'b', rotulo: 'CQ · ADE', contagem: 47 },
              { id: 't', rotulo: 'Todos os lotes', contagem: 163, todas: true },
            ]}
          />
        </Bloco>
      </Exemplo>

      <Exemplo titulo="Métricas" uso="O número que resume a tela ou pede atenção. tom='alerta' quando há algo esperando alguém; um gráfico pequeno pode ir embaixo.">
        <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-4">
          <Metrica valor={160} rotulo="cargas pendentes" detalhe="2568-1" />
          <Metrica valor={63} tom="alerta" rotulo="lotes esperando você" detalhe="62 de Hidrografia e 1 de LML">
            <LinkSeta href="#/design" className="mt-2">
              Decidir
            </LinkSeta>
          </Metrica>
          <Metrica valor={3} rotulo="concluídas hoje">
            <BarrasDia dias={DIAS} altura={28} className="mt-2" />
          </Metrica>
        </div>
      </Exemplo>

      <Exemplo titulo="Andamento" uso="Barra para totais grandes e partes empilhadas; Anel para o andamento de um item numa linha ou em destaque. A legenda só lista as partes que existem.">
        <Bloco className="gap-4">
          <div className="flex items-center gap-5">
            <Anel partes={[{ valor: 43, cor: COR.concluida }]} total={100} tamanho={64} espessura={7} centro="43%" />
            <Anel partes={[{ valor: 7, cor: COR.concluida }, { valor: 2, cor: COR.naoConforme }]} total={20} />
            <Anel partes={[{ valor: 20, cor: COR.concluida }]} total={20} />
            <Anel partes={[]} total={20} />
          </div>
          <Barra
            total={2808}
            partes={[
              { valor: 1205, cor: COR.concluida },
              { valor: 1400, cor: COR.comAlguem },
              { valor: 100, cor: COR.naFila },
            ]}
          />
          <Legenda
            itens={[
              { cor: COR.concluida, rotulo: 'concluídas' },
              { cor: COR.comAlguem, rotulo: 'com alguém' },
              { cor: COR.naFila, rotulo: 'na fila' },
              { cor: COR.vazio, rotulo: 'a atribuir' },
            ]}
          />
        </Bloco>
      </Exemplo>

      <Exemplo titulo="Lista agrupada" uso="Coleções que se navegam item a item (lotes, pessoas, fluxos). A seta aparece quando a linha leva a outra tela; ações que não navegam ficam à direita, fora do link.">
        <Lista>
          <LinhaLista href="#/design" inicio={<Anel partes={[{ valor: 8, cor: COR.concluida }]} total={168} />} titulo="2568-1" sub="LML · Aquisição e revisão" fim={<span className="tab">8/168 cargas</span>} />
          <LinhaLista
            href="#/design"
            inicio={<Anel partes={[{ valor: 1, cor: COR.concluida }, { valor: 1, cor: COR.naoConforme }]} total={4} />}
            titulo="2536-2"
            sub="Áreas densamente edificadas · Controle de qualidade"
            fim={
              <>
                <Selo tom="alerta">1 não conforme</Selo>
                <span className="tab">2/4 amostras</span>
              </>
            }
            acoes={
              <Button variant="tinted" size="icon" className="rounded-full" aria-label="Continuar no QGIS">
                <Play className="size-3.5 fill-current" />
              </Button>
            }
          />
          <LinhaLista titulo="2571-1" sub="Sua parte terminou. O lote segue quando o supervisor abrir a próxima etapa." fim={<Selo tom="sucesso">concluída</Selo>} />
        </Lista>
      </Exemplo>

      <Exemplo titulo="Tabela" uso="Dados com várias colunas comparáveis. A Tabela já traz a superfície, o cabeçalho e os fios; nas células, só alinhamento (text-right, tab) e truncate. `solta` dentro de um Bloco; `fixa` + Colunas quando o conteúdo muda.">
        <Tabela fixa largura={640}>
          <Colunas larguras={[110, undefined, 120, 140]} />
          <thead>
            <tr>
              <th>Lote</th>
              <th>Responsável</th>
              <th className="text-right">Pendentes</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="tab font-semibold">2568-1</td>
              <td>Pessoa A</td>
              <td className="tab text-right">380</td>
              <td>
                <Status s="EM_PRODUCAO" />
              </td>
            </tr>
            <tr>
              <td className="tab font-semibold">2536-2</td>
              <td className="text-muted-foreground">ninguém</td>
              <td className="tab text-right">20</td>
              <td>
                <Status s="EM_CQ" />
              </td>
            </tr>
          </tbody>
        </Tabela>
      </Exemplo>

      <Exemplo titulo="Mensagens" uso="Nota dentro da tela (o que aconteceu, o que falta); Vazio quando não há o que mostrar; Ponto para estados com cor; avisos passageiros pelo useAvisar.">
        <div className="flex flex-col gap-3">
          <Nota titulo="Uma alteração sua não ficou na CCAR" tom="alerta" acao={<Button variant="outline" size="sm">Ver</Button>}>
            A carga 2568-1 · 3417 foi concluída por outra pessoa antes da sua sincronização.
          </Nota>
          <Nota tom="info">As cargas saem sozinhas quando a etapa abre.</Nota>
          <Nota tom="sucesso">Lote distribuído para 3 pessoas.</Nota>
          <Nota tom="perigo">Sem conexão com a CCAR.</Nota>
          <Bloco>
            <TituloBloco titulo="Equipe" sub="16 pessoas com carga" acao={<LinkSeta href="#/design">Abrir Equipe</LinkSeta>} />
            <Vazio>Nenhuma carga com você agora. O supervisor atribui as cargas.</Vazio>
          </Bloco>
          <div className="flex gap-4">
            <Ponto cor="var(--sucesso)">Conectado</Ponto>
            <Ponto cor="var(--alerta)">Sem a CCAR</Ponto>
          </div>
        </div>
      </Exemplo>
    </Conteudo>
  )
}
