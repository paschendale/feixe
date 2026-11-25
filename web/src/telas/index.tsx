import type { ComponentType } from 'react'
import type { Papel } from '@/lib/api'
import Catalogo from './catalogo/Catalogo'
import Execucao from './execucao/Execucao'
import Inicio from './inicio/Inicio'
import Sobre from './Sobre'
import Supervisao from './supervisao/Supervisao'

export type Tela = {
  id: string
  rotulo: string
  // Quem vê o módulo no topo. Vazio = todos. A API barra de novo: o menu só esconde.
  papeis: Papel[]
  // Fora do topo (Sobre abre pelas iniciais).
  oculta?: boolean
  componente: ComponentType
}

// Módulos do topo (D-103), os mesmos modos do QGIS: o Início junta um painel por papel e leva a cada módulo.
const TELAS: Tela[] = [
  { id: 'inicio', rotulo: 'Início', papeis: [], componente: Inicio },
  { id: 'supervisao', rotulo: 'Supervisão', papeis: ['supervisor', 'gerente'], componente: Supervisao },
  { id: 'execucao', rotulo: 'Execução', papeis: ['apm', 'avaliador', 'supervisor'], componente: Execucao },
  { id: 'catalogo', rotulo: 'Catálogo', papeis: [], componente: Catalogo },
  { id: 'sobre', rotulo: 'Sobre', papeis: [], oculta: true, componente: Sobre },
]

export function telasDe(papeis: Papel[]): Tela[] {
  return TELAS.filter((t) => t.papeis.length === 0 || t.papeis.some((p) => papeis.includes(p)))
}
