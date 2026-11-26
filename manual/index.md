---
titulo: O Feixe
ordem: 1
---

# O Feixe

O Feixe é um plugin do QGIS para planejar, executar, controlar a qualidade e acompanhar as cargas de trabalho da produção cartográfica. Ele organiza o trabalho de cada equipe em unidades pequenas e padronizadas, mostra a cada pessoa o que é dela no próprio mapa em que ela trabalha e dá ao supervisor uma visão de quem está com o quê, em que etapa está cada lote e o que espera uma decisão.

Ele funciona com e sem rede: quem executa continua trabalhando offline, e o Feixe sincroniza sozinho quando a conexão volta.

## Duas janelas

O Feixe tem duas partes que trabalham juntas:

- **A barra do Feixe, dentro do QGIS.** Fica junto das ferramentas do QGIS e tem as ações do dia a dia, as que se repetem dezenas de vezes por hora: ir para a próxima carga, concluir, avaliar uma amostra, registrar uma ocorrência. Cada ação tem atalho de teclado.
- **O painel, no navegador.** Abre no navegador padrão do computador, servido pelo próprio plugin (nada sai da máquina). É onde se planeja, distribui, acompanha e decide: lotes, fluxos, equipe, filas, controle de qualidade.

Um clique em "Continuar no QGIS" no painel leva o mapa até a carga, e o painel acompanha o que é feito no QGIS na hora.

## Quem usa

| Papel | O que faz no Feixe |
|---|---|
| Quem executa | Recebe cargas, trabalha sobre a imagem, conclui, dá ciência das ocorrências encontradas no seu trabalho. |
| Quem avalia | Avalia as amostras do controle de qualidade e registra ocorrências no mapa. |
| Supervisor | Cria os lotes, gera as cargas, distribui o trabalho, acompanha o fluxo e decide cada passo. |
| Gerente | Acompanha o andamento. |

O papel de cada pessoa vem do cadastro de perfis do sistema de gerenciamento de bases cartográficas; o Feixe não tem cadastro próprio de usuários.

## Por onde começar

1. [Instalação e primeiro acesso](instalar.html)
2. [Conceitos](conceitos.html): carga, lote, fluxo, plano de CQ.
3. O guia do seu papel: [executar](executar.html), [avaliar](avaliar.html) ou [supervisionar](supervisionar.html).
4. [Sem rede e sincronização](offline.html) e [a barra e os atalhos](barra.html).
