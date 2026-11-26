---
titulo: Instalação e primeiro acesso
ordem: 2
---

# Instalação e primeiro acesso

Você precisa do QGIS 3.22 ou mais novo (Windows ou macOS) e do seu usuário e senha do banco de dados cartográfico. Não é preciso instalar mais nada: o Feixe usa só o que já vem com o QGIS.

## 1. Adicionar o repositório do Feixe

1. No QGIS, abra **Complementos › Gerenciar e instalar complementos**.
2. Vá em **Configurações** e, em **Repositórios de complementos**, clique em **Adicionar**.
3. Dê o nome **Feixe** e cole o endereço:

   `https://paschendale.github.io/feixe/plugins.xml`

4. Clique em **OK** e depois em **Recarregar todos os repositórios**.

Equipes que testam versões novas antes da liberação usam o canal de testes, `https://paschendale.github.io/feixe/plugins-hml.xml`, e marcam **Mostrar também os complementos experimentais**.

## 2. Instalar

Em **Todos**, procure **Feixe** e clique em **Instalar complemento**. A barra do Feixe aparece junto das ferramentas do QGIS. Atualizações chegam pelo mesmo gerenciador, como as de qualquer complemento.

Sem acesso ao repositório (por exemplo, atrás de um proxy que bloqueia o endereço), baixe o arquivo `feixe-<versão>.zip` da [página de versões](https://github.com/paschendale/feixe/releases) e use **Instalar a partir do ZIP**, no mesmo gerenciador.

## 3. Entrar com usuário e senha

1. Na barra do Feixe, clique em **Conectar ao Feixe** (o primeiro botão, com um ponto cinza).
2. Informe o mesmo usuário e senha do banco de dados cartográfico e clique em **Testar e salvar**. O Feixe testa a conexão antes de guardar: se não conectar, ele diz o motivo.
3. Na primeira vez, o QGIS pede para criar uma **senha mestra**. É ela que protege as senhas guardadas no QGIS, inclusive a do Feixe. Guarde-a: o QGIS vai pedi-la uma vez a cada sessão.

O ponto no botão mostra o estado da conexão: verde, conectado; laranja, sem conexão com o banco (o Feixe continua funcionando offline); cinza, usuário e senha não configurados.

Não há nada mais a configurar: o Feixe já sabe a qual banco se conectar.

## 4. Carregar as camadas e abrir o painel

- **Carregar as camadas do Feixe** monta no projeto o grupo Feixe com as camadas do seu papel. A seta ao lado troca o modo: Executar, Avaliar ou Supervisionar.
- **Abrir o Feixe no navegador** abre o painel. Ele abre no navegador padrão e só funciona enquanto o QGIS está aberto, porque é o próprio plugin que o serve.

Pronto. Siga para o guia do seu papel: [executar](executar.html), [avaliar](avaliar.html) ou [supervisionar](supervisionar.html).

## Problemas comuns

| O que acontece | O que fazer |
|---|---|
| "Não conectou" ao testar a senha | Confira usuário e senha. Fora da rede do órgão o banco não responde: conecte-se à rede e tente de novo. |
| O QGIS pede a senha mestra toda vez | É o comportamento do QGIS: uma vez por sessão. |
| O painel não abre | Confira se o QGIS está aberto e clique de novo em **Abrir o Feixe no navegador**. |
| Não aparecem camadas de supervisão | O modo Supervisionar é só para quem tem perfil de supervisor. |
