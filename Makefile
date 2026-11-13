.PHONY: help install test cov lint format build clean

help: ## Lista os alvos
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-10s %s\n", $$1, $$2}'

install: ## Instala dependências (inclui dev)
	uv sync

test: ## Roda os testes
	uv run pytest -q

cov: ## Testes com cobertura
	uv run pytest -q --cov --cov-report=term-missing

lint: ## Verifica estilo
	uv run ruff check .
	uv run ruff format --check .

format: ## Formata o código
	uv run ruff check --fix .
	uv run ruff format .

build: clean ## Gera sdist e wheel em dist/
	uv run python -m build

clean: ## Remove artefatos de build
	rm -rf dist/ build/ *.egg-info/
