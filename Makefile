.PHONY: help install dev test lint format typecheck check audit up down logs

help:
	@echo "install    uv sync (dev dependencies)"
	@echo "dev        run the API locally with reload"
	@echo "test       run pytest with coverage gate"
	@echo "lint       ruff lint + format check"
	@echo "format     ruff autofix and format"
	@echo "typecheck  mypy --strict"
	@echo "check      lint + typecheck + test"
	@echo "audit      pip-audit on the locked dependencies"
	@echo "up         docker compose up --build -d"
	@echo "down       docker compose down"

install:
	uv sync

dev:
	uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy

check: lint typecheck test

audit:
	uv export --frozen --no-hashes --no-emit-project --all-groups > requirements-audit.txt
	uvx pip-audit -r requirements-audit.txt
	rm -f requirements-audit.txt

up:
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f api
