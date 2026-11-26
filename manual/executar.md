---
titulo: Para quem executa
ordem: 4
---

# Para quem executa

## O dia a dia

1. Abra o QGIS com a sua imagem e os seus dados, clique em **Carregar as camadas do Feixe** e deixe o modo **Executar**.
2. Clique em **Próxima carga** (Alt+Shift+N). O mapa enquadra a carga, que fica com contorno magenta em **Minhas cargas**.
3. Trabalhe na carga normalmente, com as ferramentas do QGIS.
4. Terminou? **Concluir carga** (Alt+Shift+C) conclui a atual e já leva para a próxima.

Se uma carga precisa esperar (falta insumo, dúvida para o supervisor), **Pular** (Alt+Shift+P) deixa para depois e vai para a próxima; ela volta quando acabarem as outras do lote.

A camada **Minhas cargas** mostra o seu trabalho sem esconder a imagem: a atual só com contorno, as pendentes com uma hachura leve, as concluídas recentes em verde e as mais antigas em cinza. **Meus lotes** mostra a moldura dos lotes em que você tem cargas.

## Concluiu errado?

No painel, em **Execução › Minhas cargas**, a aba **Concluídas** permite desfazer uma conclusão por até 24 horas. Também dá para marcar ou desmarcar pela tabela de atributos de Minhas cargas: o Feixe aplica as mesmas regras da barra.

## Quando o lote acaba

O supervisor pode ter deixado uma fila de lotes para você. Quando a última carga de um lote é concluída, a próxima da fila chega sozinha, mesmo offline. Sem fila, o supervisor recebe o aviso e distribui o próximo.

## Ocorrências para ciência

Quando o controle de qualidade encontra um problema numa carga sua, a ocorrência aparece em **Ocorrências para ciência**, no QGIS, e em **Execução › Para ciência**, no painel. Veja o ponto e a anotação e dê **Ciente** (Alt+Shift+I), uma a uma ou o lote todo. Ciência é retorno para o seu aprendizado: a correção é feita depois, na etapa de correção.

## Correção de inspeção

Se você recebe uma carga de correção, ela é o lote inteiro com todas as ocorrências a tratar:

1. **Próxima ocorrência** (Alt+Shift+J) mostra a próxima por tratar, sem mudar a escala.
2. Corrija no mapa e marque **Tratada** (Alt+Shift+T): o Feixe vai para a seguinte.
3. Na última, a carga se conclui e o lote volta ao supervisor.

## No painel

**Execução** reúne Minhas cargas (pendentes, concluídas, hoje), Minhas amostras, Correção e Para ciência. O **Início** resume o seu andamento e mostra o que pede a sua atenção.
