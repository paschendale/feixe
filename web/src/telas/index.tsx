import type { ComponentType } from 'react'
import { ClipboardList, Info, ListOrdered, Map, Network, Settings2, Users } from 'lucide-react'
import type { Papel } from '@/lib/api'
import EmConstrucao from './EmConstrucao'
import Atividades from './atividades/Atividades'
import Equipe from './equipe/Equipe'
import Folhas from './folhas/Folhas'
import Fluxos from './fluxos/Fluxos'
import MinhasCargas from './MinhasCargas'
import Sobre from './Sobre'

export type Tela = {
  id: string
  rotulo: string
  icone: ComponentType<{ className?: string }>
  // Quem vê a tela no menu. Vazio = todos. A API barra de novo: o menu só esconde.
  papeis: Papel[]
  componente: ComponentType
}

const emBreve = (item: string) => () => <EmConstrucao item={item} />

// Navegação por papel (D-72). Cada item da fase B troca o seu `emBreve` pela tela de verdade.
export const TELAS: Tela[] = [
  { id: 'minhas-cargas', rotulo: 'Minhas cargas', icone: ClipboardList, papeis: ['apm', 'avaliador', 'supervisor'], componente: MinhasCargas },
  { id: 'folhas', rotulo: 'Folhas', icone: Map, papeis: ['supervisor', 'gerente'], componente: Folhas },
  { id: 'equipe', rotulo: 'Equipe', icone: Users, papeis: ['supervisor'], componente: Equipe },
  { id: 'filas', rotulo: 'Filas', icone: ListOrdered, papeis: ['supervisor'], componente: emBreve('B8') },
  { id: 'fluxos', rotulo: 'Fluxos', icone: Network, papeis: ['supervisor', 'gerente'], componente: Fluxos },
  { id: 'atividades', rotulo: 'Atividades', icone: Settings2, papeis: [], componente: Atividades },
  { id: 'sobre', rotulo: 'Sobre', icone: Info, papeis: [], componente: Sobre },
]

export function telasDe(papeis: Papel[]): Tela[] {
  return TELAS.filter((t) => t.papeis.length === 0 || t.papeis.some((p) => papeis.includes(p)))
}
