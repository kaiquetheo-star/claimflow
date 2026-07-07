# Claimflow Autopilot

B2B Autopilot Agent for autonomous insurance claims processing, powered by **LangGraph**, **FastAPI**, and **Alibaba Cloud DashScope (Qwen)**.

Claimflow ingests raw claim submissions (e.g. email text), extracts structured data via LLM, assesses risk, and routes each claim through an automated approval pipeline or escalates it to human review.

---

## Architecture

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────────────────┐
│  FastAPI    │────▶│  LangGraph Agent │────▶│  Alibaba Cloud              │
│  REST API   │     │  Pipeline        │     │  DashScope (Qwen) + OSS     │
└─────────────┘     └──────────────────┘     └─────────────────────────────┘
                            │
                    ┌───────┴────────┐
                    │  triage        │
                    │  risk_assess   │
                    │  human_review  │
                    │  approval      │
                    └────────────────┘
```

> **Note:** Detailed architecture documentation (sequence diagrams, deployment topology, data flows) will be added as the system evolves.

### Agent Pipeline

| Node              | Responsibility                                      |
|-------------------|-----------------------------------------------------|
| `triage`          | Parse raw input and extract structured claim fields |
| `risk_assessment` | Compute a normalized risk score [0.0 – 1.0]         |
| `human_review`    | Escalate high-risk claims to an adjuster            |
| `approval`        | Auto-approve low-risk claims                        |

---

## Requirements

- Python 3.11+
- `make`
- Alibaba Cloud account with DashScope and OSS access

---

## Setup

### 1. Clone and configure environment

```bash
git clone <repository-url>
cd claimflow
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install dependencies

```bash
make install
```

This creates a `.venv` virtual environment and installs the package in editable mode with dev dependencies.

### 3. Run the development server

```bash
make run
```

The API will be available at:

- **Docs (Swagger):** http://localhost:8000/api/v1/docs
- **Health check:** http://localhost:8000/api/v1/health

### 4. Frontend (Streamlit dashboard)

Run the backend and frontend in separate terminals for the full demo experience:

```bash
# Terminal 1 - Backend
make run

# Terminal 2 - Frontend
make run-frontend
```

Open the dashboard at **http://localhost:8501**.

![Claimflow Dashboard](docs/screenshot.png)

---

## Makefile Commands

| Command       | Description                              |
|---------------|------------------------------------------|
| `make install`| Create venv and install all dependencies |
| `make lint`   | Run ruff linter and format checks        |
| `make test`   | Run pytest test suite                    |
| `make run`          | Start uvicorn development server         |
| `make run-frontend` | Start Streamlit demo dashboard (port 8501) |
| `make clean`        | Remove venv and build artifacts          |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

| Variable                          | Required | Default                  | Description                              |
|-----------------------------------|----------|--------------------------|------------------------------------------|
| `DASHSCOPE_API_KEY`               | Yes      | —                        | DashScope API key for Qwen LLM           |
| `ALIBABA_CLOUD_ACCESS_KEY_ID`     | Yes      | —                        | Alibaba Cloud IAM access key ID          |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | Yes      | —                        | Alibaba Cloud IAM access key secret      |
| `OSS_BUCKET_NAME`                 | Yes      | —                        | OSS bucket for claim document storage    |
| `OSS_ENDPOINT`                    | Yes      | —                        | OSS endpoint URL                         |
| `API_V1_STR`                      | No       | `/api/v1`                | API route prefix                         |
| `PROJECT_NAME`                    | No       | `Claimflow Autopilot`    | Display name in OpenAPI docs             |
| `LOG_LEVEL`                       | No       | `INFO`                   | Root logging level                       |
| `ENVIRONMENT`                     | No       | `development`            | `development` / `staging` / `production` |

---

## Project Structure

```
claimflow/
├── src/
│   └── claimflow/
│       ├── api/              # FastAPI app, routers
│       ├── agents/           # LangGraph state & graph
│       ├── core/             # Config, logging
│       └── models/           # Pydantic schemas
├── tests/
├── .env.example
├── Makefile
├── pyproject.toml
└── README.md
```

---

## License

Proprietary — All rights reserved.
