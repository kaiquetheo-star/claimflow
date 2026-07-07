# Claimflow Autopilot

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

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

📐 **Full architecture documentation:** [docs/architecture.md](docs/architecture.md) — includes the Mermaid diagram (4 layers: Frontend, Backend, LangGraph, External Services), data-flow walkthrough, and security design.

![Claimflow Architecture](docs/architecture.png)

> **Editable diagram source:** The Mermaid diagram in [docs/architecture.md](docs/architecture.md) can be copied to [mermaid.live](https://mermaid.live) to export an updated PNG/SVG.

### Agent Pipeline

| Node              | Responsibility                                      |
|-------------------|-----------------------------------------------------|
| `triage`          | Parse raw input and extract structured claim fields |
| `investigation`   | Weather verification via Open-Meteo when needed     |
| `risk_assessment` | Compute a normalized risk score [0.0 – 1.0]         |
| `human_review`    | Escalate high-risk claims to an adjuster            |
| `approval`        | Auto-approve low-risk claims                        |
| `rejected`        | Auto-reject high-fraud claims                         |

See [docs/architecture.md](docs/architecture.md) for the complete 6-node pipeline.

---

## Requirements

- Python 3.11+
- `make`
- Alibaba Cloud account with DashScope and OSS access

📦 **Deployment guide:** [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

---

## Setup

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for the full deployment guide. Quick start:

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
├── docs/
│   ├── architecture.md       # System architecture + Mermaid diagram
│   ├── architecture.png      # Architecture diagram image
│   ├── DEPLOYMENT.md         # Setup and deployment guide
│   ├── ALIBABA_CLOUD_PROOF.md
│   └── screenshot.png        # Dashboard preview
├── tests/
├── .env.example
├── Makefile
├── pyproject.toml
└── README.md
```

---

## Alibaba Cloud Integration

Claimflow is built on **Alibaba Cloud** for AI inference, object storage, and secure API access:

| Service | Purpose | Models / SDK |
|---------|---------|--------------|
| **Qwen Cloud (DashScope)** | Text extraction, risk assessment, vision analysis | `qwen-max`, `qwen-vl-max` |
| **Alibaba Cloud OSS** | Production storage for claim images and documents | `alibabacloud-oss-v2` |
| **Alibaba Cloud RAM** | Least-privilege AccessKeys for API authentication | RAM user `claimflow-dev` |

Full proof documentation: **[docs/ALIBABA_CLOUD_PROOF.md](docs/ALIBABA_CLOUD_PROOF.md)**

Central integration module: [`src/claimflow/services/alibaba_cloud_integration.py`](src/claimflow/services/alibaba_cloud_integration.py)

### Verify the integration

Start the API and call the health endpoint:

```bash
make run
curl http://localhost:8000/api/v1/health | jq
```

The response includes `alibaba_cloud_services` with live status for DashScope (Qwen Cloud), OSS, and RAM credentials. See [docs/ALIBABA_CLOUD_PROOF.md](docs/ALIBABA_CLOUD_PROOF.md) for the expected JSON schema and console verification steps.

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
