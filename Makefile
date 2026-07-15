.PHONY: install lint test coverage run run-frontend migrate migrate-down migrate-revision \
	db-up clean help

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn
STREAMLIT := $(VENV)/bin/streamlit
ALEMBIC := $(VENV)/bin/alembic
# Prefer CLAIMFLOW_PORT from the environment, then .env, then 8000.
CLAIMFLOW_PORT ?= $(shell sed -n 's/^[[:space:]]*CLAIMFLOW_PORT=//p' .env 2>/dev/null | tail -1)
ifeq ($(strip $(CLAIMFLOW_PORT)),)
CLAIMFLOW_PORT := 8000
endif

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install: ## Create virtualenv and install dependencies
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

lint: ## Run ruff linter and formatter checks
	$(RUFF) check src tests
	$(RUFF) format --check src tests

lint-fix: ## Auto-fix lint issues with ruff
	$(RUFF) check --fix src tests
	$(RUFF) format src tests

test: ## Run pytest test suite
	$(PYTEST) -v

coverage: ## Run tests with coverage report (terminal + htmlcov/)
	$(PYTEST) --cov=claimflow --cov-report=term-missing --cov-report=html -v

run: ## Start the FastAPI development server
	@$(PYTHON) -c "import socket,sys; p=int('$(CLAIMFLOW_PORT)'); \
s=socket.socket(); s.settimeout(0.5); busy=(s.connect_ex(('127.0.0.1',p))==0); s.close(); \
sys.exit(0 if not busy else (print(f'Port {p} is already in use. Stop the other process or set CLAIMFLOW_PORT in .env') or 1))"
	$(UVICORN) claimflow.api.main:app --reload --host 0.0.0.0 --port $(CLAIMFLOW_PORT) --app-dir src

BACKEND_URL ?= http://localhost:8001

run-frontend: ## Start the Streamlit demo dashboard
	BACKEND_URL="$(BACKEND_URL)" $(STREAMLIT) run streamlit_app.py --server.port 8501

db-up: ## Start PostgreSQL via Docker Compose
	docker compose up -d postgres

migrate: ## Apply Alembic migrations (alembic upgrade head)
	$(ALEMBIC) upgrade head

migrate-down: ## Roll back the latest Alembic migration
	$(ALEMBIC) downgrade -1

migrate-revision: ## Create a new Alembic revision (MSG="description" required)
	@test -n "$(MSG)" || (echo 'Usage: make migrate-revision MSG="add column foo"' && exit 1)
	$(ALEMBIC) revision --autogenerate -m "$(MSG)"

clean: ## Remove virtualenv and build artifacts
	rm -rf $(VENV) build dist *.egg-info .pytest_cache .ruff_cache .coverage htmlcov
