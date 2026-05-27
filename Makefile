.PHONY: help install dev backend frontend check lint typecheck test gen-types docker-build docker-up docker-down clean

help:
	@echo "Skoll — common targets"
	@echo "  make install       — install backend (uv) + frontend (pnpm) deps"
	@echo "  make dev           — run backend and frontend in watch mode"
	@echo "  make backend       — run backend only (FastAPI + uvicorn)"
	@echo "  make frontend      — run frontend only (Vite dev server)"
	@echo "  make check         — full CI suite (lint + typecheck + test + security)"
	@echo "  make gen-types     — regenerate TS types from contracts/openapi.yaml"
	@echo "  make docker-up     — bring up searxng + sandbox containers"
	@echo "  make clean         — remove caches and build artifacts"

install:
	cd backend && uv sync --all-extras --dev
	pnpm install

dev:
	@echo "Starting backend + frontend; press Ctrl-C to stop both."
	$(MAKE) -j 2 backend frontend

backend:
	cd backend && uv run uvicorn skoll.app:app --host $${SKOLL_HOST:-127.0.0.1} --port $${SKOLL_PORT:-8000} --reload

frontend:
	pnpm --filter frontend dev

lint:
	cd backend && uv run ruff check src tests
	cd backend && uv run ruff format --check src tests
	pnpm --filter frontend lint

typecheck:
	cd backend && uv run mypy src
	pnpm --filter frontend typecheck

test:
	cd backend && uv run pytest -m "not integration"
	pnpm --filter frontend test --run

security:
	cd backend && uv run bandit -r src -c ../pyproject.toml
	gitleaks detect --no-banner --redact

check: lint typecheck test security
	@echo "✅ All checks passed."

gen-types:
	@echo "Generating TS types from contracts/openapi.yaml..."
	pnpm --filter frontend gen:types

docker-build:
	docker compose build

docker-up:
	docker compose up -d searxng sandbox

docker-down:
	docker compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .mypy_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
	rm -rf backend/dist frontend/dist .skoll_cache
