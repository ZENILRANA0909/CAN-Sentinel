# CAN-Sentinel - common tasks.
#
#   make help     list every target
#   make install  set up both toolchains
#   make dev      run backend and dashboard locally
#   make verify   run every quality gate

SHELL := /bin/bash
.DEFAULT_GOAL := help

BACKEND  := backend
FRONTEND := frontend
VENV     := $(BACKEND)/.venv

# The venv layout differs between Windows and POSIX.
ifeq ($(OS),Windows_NT)
PY  := $(VENV)/Scripts/python.exe
PIP := $(VENV)/Scripts/pip.exe
else
PY  := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
endif

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------- #
# Setup
# --------------------------------------------------------------------------- #
.PHONY: install
install: install-backend install-frontend ## Install both toolchains

.PHONY: install-backend
install-backend: ## Create the virtualenv and install Python dependencies
	python -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r $(BACKEND)/requirements-dev.txt

.PHONY: install-frontend
install-frontend: ## Install dashboard dependencies
	cd $(FRONTEND) && npm install

.PHONY: env
env: ## Create .env from the example if it does not exist
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")

# --------------------------------------------------------------------------- #
# Development
# --------------------------------------------------------------------------- #
.PHONY: dev-backend
dev-backend: ## Run the API with auto-reload on :8000
	cd $(BACKEND) && ../$(PY) -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: dev-frontend
dev-frontend: ## Run the dashboard dev server on :5173
	cd $(FRONTEND) && npm run dev

.PHONY: dev
dev: ## Run backend and dashboard together (Ctrl-C stops both)
	@echo "Backend  -> http://localhost:8000/docs"
	@echo "Dashboard-> http://localhost:5173"
	@trap 'kill 0' EXIT INT TERM; $(MAKE) dev-backend & $(MAKE) dev-frontend & wait

.PHONY: simulator
simulator: ## Run the standalone traffic generator (prints frames)
	$(PY) simulator/can_sentinel_sim.py --mode NORMAL --dry-run

.PHONY: demo
demo: ## Drive the scripted attack demonstration against a running instance
	$(PY) scripts/demo.py

# --------------------------------------------------------------------------- #
# Quality gates
# --------------------------------------------------------------------------- #
.PHONY: test
test: ## Run the backend test-suite
	cd $(BACKEND) && ../$(PY) -m pytest -q

.PHONY: test-cov
test-cov: ## Run the backend tests with a coverage report
	cd $(BACKEND) && ../$(PY) -m pytest --cov=app --cov-report=term-missing

.PHONY: test-frontend
test-frontend: ## Run the dashboard tests
	cd $(FRONTEND) && npx vitest run

.PHONY: test-e2e
test-e2e: ## Run the black-box tests against a running instance (set CAN_SENTINEL_URL)
	CAN_SENTINEL_URL=http://localhost:8080 $(PY) -m pytest tests/ -v

.PHONY: lint
lint: ## Lint backend and dashboard
	cd $(BACKEND) && ../$(PY) -m ruff check .
	cd $(FRONTEND) && npx eslint .

.PHONY: format
format: ## Apply safe lint fixes to the backend
	cd $(BACKEND) && ../$(PY) -m ruff check --fix .

.PHONY: typecheck
typecheck: ## Typecheck the dashboard
	cd $(FRONTEND) && npx tsc -b --noEmit

.PHONY: build
build: ## Build the dashboard for production
	cd $(FRONTEND) && npm run build

.PHONY: verify
verify: ## Run every quality gate
	bash scripts/verify.sh

# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
.PHONY: migrate
migrate: ## Apply database migrations
	cd $(BACKEND) && ../$(PY) -m alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll every migration back
	cd $(BACKEND) && ../$(PY) -m alembic downgrade base

# --------------------------------------------------------------------------- #
# Housekeeping
# --------------------------------------------------------------------------- #
.PHONY: clean
clean: ## Remove caches, build output and generated data
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf $(FRONTEND)/dist $(FRONTEND)/coverage $(BACKEND)/htmlcov $(BACKEND)/.coverage
	rm -f data/*.db data/*.db-wal data/*.db-shm logs/*.log logs/*.log.*
	@echo "Cleaned."
