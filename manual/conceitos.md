---
titulo: Conceitos
ordem: 3
---

# Conceitos

## Carga de trabalho

A unidade de trabalho do Feixe. É uma célula da **grade estatística** oficial (em projeção de áreas iguais), inteira, no tamanho definido pela atividade: por exemplo 5 km para hidrografia e 2,5 km para áreas densamente edificadas. Toda carga tem a mesma área em qualquer lugar do país, um geocódigo nacional e um responsável. Carga sem responsável está esperando o supervisor distribuir.

Como as cargas são pequenas e iguais, o andamento é medido de forma justa entre pessoas, temas e regiões.

## Lote

Um agrupamento de cargas. O tipo mais comum é a **folha** (uma folha da articulação 1:100.000, como 2534). Um **lote livre** é um polígono qualquer: uma bacia, um município, uma área desenhada. As cargas entram no lote pelo centroide da célula, sem cortar a célula na borda.

## Fluxo e etapas

Cada equipe configura um **fluxo** por projeto e tema: a sequência de etapas pelas quais um lote passa (aquisição, controle de qualidade, revisão, correção de inspeção, correção topológica, envio à inspeção externa). Cada passagem por uma etapa tem número: "2534-3" é a folha 2534 na revisão 3.

O lote só muda de etapa quando o supervisor decide. O Feixe mostra o que está pronto para andar e sugere o próximo passo, mas nunca avança sozinho.

## Status

Além da etapa local, cada lote tem um status comum a todas as equipes, derivado da etapa: planejado, em produção, em controle de qualidade, entregue à inspeção externa, concluído ou devolvido.

## Controle de qualidade

O controle de qualidade segue a amostragem por área do manual de avaliação da qualidade de dados geoespaciais:

- O **plano** de cada elemento de qualidade (comissão, omissão, nome geográfico, classificação, consistência topológica…) calcula o tamanho da amostra pelo número de células do lote, pelo nível de inspeção e pelo limite de qualidade aceitável, e sorteia as células.
- Cada amostra é avaliada como **conforme** ou **não conforme**. Os problemas encontrados viram **ocorrências**, pontos no mapa com uma anotação.
- O **resultado** do plano compara as não conformidades com o número de aceitação, e o nível de conformidade é comparado com a fração crítica.
- Quem executou recebe as ocorrências do seu trabalho e dá **ciência**: é retorno, não correção. A revisão seguinte é feita por outra pessoa, que não vê as ocorrências anteriores, salvo se o supervisor incluí-las.
- Na **correção de inspeção**, a equipe varre todas as ocorrências do lote e marca cada uma como tratada.
