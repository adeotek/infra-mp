# HomeLab Manager — common development commands.
# Uses `uv` as the package manager. Run `make help` for a quick overview.

.DEFAULT_GOAL := help

.PHONY: help install dev migrate migration test lint format format-check check build up down logs clean

help: ## Show available targets
	@echo "HomeLab Manager — development commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies (uv sync)
	uv sync

dev: ## Run the dev server with hot reload
	uv run uvicorn app.main:app --reload

migrate: ## Apply database migrations
	uv run alembic upgrade head

migration: ## Generate a migration (usage: make migration m="add column")
	uv run alembic revision --autogenerate -m "$(m)"

test: ## Run the test suite
	uv run pytest

lint: ## Lint with ruff
	uv run ruff check .

format: ## Auto-format with ruff
	uv run ruff format .

format-check: ## Check formatting without changing files
	uv run ruff format --check .

check: lint format-check test ## Run all checks (lint + format + tests)
	@echo "All checks passed"

build: ## Build the Docker image
	docker build -t homelab-manager:latest .

up: ## Start the app via docker compose (detached)
	docker compose up -d

down: ## Stop the docker compose stack
	docker compose down

logs: ## Tail docker compose logs
	docker compose logs -f

clean: ## Remove Python cache directories
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
