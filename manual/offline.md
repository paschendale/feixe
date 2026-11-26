---
titulo: Sem rede e sincronização
ordem: 7
---

# Sem rede e sincronização

O Feixe guarda no computador de cada pessoa uma cópia do trabalho dela: as cargas, a fila, as amostras e as ocorrências. Tudo o que quem executa ou avalia faz é gravado primeiro nessa cópia, e o Feixe envia ao banco em segundo plano. Por isso a barra responde na hora, com ou sem rede.

## Sem rede

- O ponto do botão **Conectar** fica laranja e o QGIS avisa que o Feixe está offline.
- Quem executa e quem avalia continuam trabalhando normalmente: próxima carga, concluir, pular, desfazer, avaliar, registrar ocorrência, ciente, tratada.
- O que é feito fica guardado e vai quando a conexão voltar. O Feixe testa a conexão sozinho a cada minuto.
- A supervisão precisa do banco: sem ele, o painel avisa e mostra só o que é da execução.

## Sincronizar

A sincronização é automática. **Sincronizar agora** (Alt+Shift+V) força uma rodada: envia o que você fez e traz o que mudou (cargas novas, a sua fila, redistribuições).

Se o supervisor tirou uma carga da sua mão, ela some do seu mapa na próxima sincronização.

## Quando há conflito

Se a mesma carga mudou no banco e no seu computador, vale a ação mais recente, pela hora em que foi feita (não pela hora em que chegou). Se uma ação sua não vale mais (por exemplo, a etapa foi encerrada enquanto você estava offline), o Feixe desfaz a sua cópia e avisa no Início do painel. Todos os casos ficam registrados para o supervisor.
