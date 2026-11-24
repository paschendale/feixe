"""Offline e sincronização (fase C, D-111).

- `workspace`: o GeoPackage local por ambiente e usuário, com o espelho da execução, a outbox e o sync_log (C1);
- `esquema`: as tabelas do workspace e o núcleo do GeoPackage;
- `geometria`: WKB e blob do GeoPackage em Python puro.

As funções da execução sobre o workspace ficam em `core/dados/local/`, ao lado das da CCAR.
"""
