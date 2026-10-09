# Feixe

Plugin QGIS para controle e acompanhamento de cargas de trabalho da produção cartográfica do IBGE (CCAR e GGCs): planejamento, execução, controle de qualidade e acompanhamento, com funcionamento híbrido (online na rede do IBGE, offline fora dela).

> Projeto em bootstrap. Nada aqui está pronto para uso.

## Como funciona

- O plugin roda dentro do QGIS (3.22 ou superior, Windows ou macOS) e só depende do que o QGIS traz: PyQt5, `qgis.core`, `psycopg2`, `sqlite3`.
- A interface rica é uma página web (React) servida por um servidor HTTP local que o próprio plugin sobe em `127.0.0.1`, aberta no navegador padrão. Dentro do QGIS fica um dock mínimo com as ações de alta frequência.
- Os dados vivem no banco da CCAR (schema `mapcartacomp`), com um workspace local por usuário para trabalho offline e sincronização quando a rede do IBGE responde.

## Desenvolvimento

```bash
make setup        # venv com ruff e pytest; dependências do front (pnpm)
make lint test    # qualidade e testes que não precisam do QGIS
make web          # compila o front para feixe/web/dist
make deploy-local # link simbólico do plugin no perfil padrão do QGIS (macOS)
make zip          # empacota feixe-<versao>.zip
```

Conexão ao banco: o plugin usa uma conexão PostGIS já cadastrada no QGIS (com a senha guardada no Authentication Manager) escolhida nas configurações do Feixe, por ambiente (desenvolvimento, homologação, produção).

## Licença

GPL-3.0. Veja `LICENSE`.
