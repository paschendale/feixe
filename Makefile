# Alvos de desenvolvimento do Feixe. Python mínimo do plugin é 3.9 (QGIS 3.22); o venv local serve só para lint e testes.
VENV ?= .venv
PY ?= $(VENV)/bin/python
QGIS_PLUGINS ?= $(HOME)/Library/Application\ Support/QGIS/QGIS3/profiles/default/python/plugins
VERSAO := $(shell sed -n 's/^version=//p' feixe/metadata.txt)

.PHONY: setup lint fmt test web web-dev ambiente-dev deploy-local zip clean

setup:
	python3 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip ruff pytest
	cd web && pnpm install --frozen-lockfile || pnpm install

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

fmt:
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

test:
	$(PY) -m pytest

web:
	cd web && pnpm build

web-dev:
	cd web && pnpm dev

ambiente-dev:
	python3 -c "import json; d=json.load(open('config/ambientes.json'))['dev']; json.dump(d, open('feixe/ambiente.json','w'), indent=2)"

deploy-local: ambiente-dev
	mkdir -p $(QGIS_PLUGINS)
	rm -rf $(QGIS_PLUGINS)/feixe
	ln -s $(CURDIR)/feixe $(QGIS_PLUGINS)/feixe
	@echo "feixe -> $(QGIS_PLUGINS)/feixe (reinicie o QGIS ou use o Plugin Reloader)"

zip: web ambiente-dev
	rm -f dist/feixe-$(VERSAO).zip
	mkdir -p dist
	cd . && zip -qr dist/feixe-$(VERSAO).zip feixe -x "*/__pycache__/*" "*.pyc"
	@echo dist/feixe-$(VERSAO).zip

clean:
	rm -rf dist feixe/web/dist web/node_modules
