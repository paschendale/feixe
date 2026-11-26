---
titulo: Para quem supervisiona
ordem: 6
---

# Para quem supervisiona

O trabalho do supervisor acontece quase todo no painel, em **Supervisão**. O QGIS entra para ver no mapa: o modo **Supervisionar** mostra as cargas por responsável, as cargas a atribuir e os lotes.

## Preparar

- **Fluxos.** Em Supervisão › Fluxos, monte o fluxo de cada tema: as etapas, em ordem, cada uma ligada a uma atividade do catálogo. Na etapa de controle de qualidade ficam o padrão do plano (nível de inspeção, limite de qualidade aceitável e fração crítica).
- **Catálogo.** Temas, atividades (com o tamanho da célula) e elementos de controle de qualidade são nacionais; o Catálogo mostra o que existe.

## Criar lotes

Em **Supervisão › Lotes**:

- **Novas folhas**: busque por MI, nome ou nomenclatura, ou escolha no mapa do QGIS (clique numa folha, ou Ctrl e arraste um retângulo para várias).
- **Novo lote livre**: selecione no QGIS os polígonos (bacias, municípios, uma área desenhada) na camada ativa e use a seleção. Com várias feições, cada uma vira um lote, com o nome tirado de um campo da camada; ou junte todas num lote só.

Ao criar, escolha o fluxo. O Feixe abre a primeira etapa e gera as cargas pela grade.

Um lote criado por engano pode ser excluído enquanto não tem trabalho feito (pela gaveta do lote ou marcando vários na lista).

## Distribuir

**Distribuir** (na gaveta do lote, ou marcando vários lotes na lista) entrega as cargas a uma pessoa e, se quiser, monta a **fila** dela: os lotes seguintes chegam sozinhos quando ela termina o atual. **Supervisão › Filas** mostra e reordena as filas, e **Equipe** mostra quem está com o quê e permite repassar o trabalho de alguém (férias, troca de equipe).

## Acompanhar e decidir

**Esperando você** junta tudo o que espera uma decisão sua: lotes que terminaram uma etapa, controles de qualidade avaliados, amostras sem avaliador. Para cada grupo:

- **Abrir a próxima etapa**: o lote anda no fluxo, com as cargas geradas, e já pode ser distribuído.
- No controle de qualidade, o resultado por elemento ("Comissão: 3 não conformes, aceita até 2") e o nível de conformidade. **Aprovar** abre a etapa seguinte; **Nova revisão** abre a próxima revisão com outra pessoa e, se quiser, com as correções a fazer à vista.
- **Encerrar**, quando o lote chegou ao fim do fluxo.

A observação é sempre opcional, e toda decisão fica no histórico do lote. A **gaveta** de cada lote (clique no lote) mostra as etapas, as cargas, as amostras, as ocorrências e o histórico, e permite iniciar, concluir, pular ou reabrir uma etapa.

## Controle de qualidade

Ao abrir uma etapa de controle de qualidade, o Feixe cria os planos com o padrão do fluxo e sorteia as amostras, sem repetir células sorteadas em passagens anteriores. Dá para trocar os parâmetros enquanto nada foi avaliado.

Para distribuir as amostras, escolha os avaliadores e o peso de cada um (em porcentagem ou em número de amostras). O Feixe lembra a equipe do último controle de qualidade e oferece reutilizá-la. As amostras de todos os lotes escolhidos são somadas e repartidas, cada pessoa com uma fatia de cada elemento, e quem fez a aquisição de um lote fica de fora das amostras desse lote.

## Conflitos

Quando duas pessoas mudam a mesma coisa, uma delas offline, vale a última ação, e nada se perde sem registro. **Supervisão › Conflitos** mostra cada caso, com os dois valores, quem e quando.
