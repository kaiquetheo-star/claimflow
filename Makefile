.PHONY: install install-playwright lint test coverage run run-frontend \
	capture-proofs record-demo clean help

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
PYTEST := $(VENV)/bin/pytest
UVICORN := $(VENV)/bin/uvicorn
STREAMLIT := $(VENV)/bin/streamlit

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Create virtualenv and install dependencies
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

install-playwright: ## Install Playwright Chromium browser for automation scripts
	$(PYTHON) -m playwright install chromium

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
	$(UVICORN) claimflow.api.main:app --reload --host 0.0.0.0 --port 8000 --app-dir src

run-frontend: ## Start the Streamlit demo dashboard
	$(STREAMLIT) run streamlit_app.py --server.port 8501

capture-proofs: ## Capture Alibaba Cloud console screenshots (headed browser)
	$(PYTHON) scripts/capture_alibaba_proofs.py

record-demo: ## Record automated hackathon demo video
	$(PYTHON) scripts/record_demo.py

clean: ## Remove virtualenv and build artifacts
	rm -rf $(VENV) build dist *.egg-info .pytest_cache .ruff_cache .coverage htmlcov
