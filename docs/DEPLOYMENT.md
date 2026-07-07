# Claimflow Deployment Guide

Minimal setup instructions for local development and hackathon demos.

---

## Prerequisites

- **Python 3.11+** (tested on 3.12)
- **make**
- Alibaba Cloud account with:
  - DashScope API key (Qwen models)
  - RAM AccessKeys (OSS access)

---

## 1. Local Development Setup

```bash
git clone <repository-url>
cd claimflow
cp .env.example .env
# Edit .env with your credentials
make install
```

`make install` creates a `.venv` virtual environment and installs the package in editable mode with dev dependencies.

---

## 2. Required Environment Variables

Copy `.env.example` to `.env`. At minimum, set:

| Variable | Required | Description |
|----------|----------|-------------|
| `DASHSCOPE_API_KEY` | Yes | DashScope API key for Qwen models |
| `ALIBABA_CLOUD_ACCESS_KEY_ID` | Yes | RAM AccessKey ID |
| `ALIBABA_CLOUD_ACCESS_KEY_SECRET` | Yes | RAM AccessKey Secret |
| `OSS_BUCKET_NAME` | Yes | OSS bucket name (even when using local storage) |
| `OSS_ENDPOINT` | Yes | OSS endpoint URL |

### Optional but useful

| Variable | Default | Description |
|----------|---------|-------------|
| `STORAGE_BACKEND` | `local` | `local` or `oss` |
| `LLM_MODEL_NAME` | `qwen-max` | Primary text model |
| `VISION_MODEL_NAME` | `qwen-vl-max` | Primary vision model |
| `RISK_THRESHOLD` | `0.7` | Human-review routing threshold |
| `REJECT_THRESHOLD` | `0.9` | Auto-reject threshold |
| `DATABASE_URL` | — | PostgreSQL for persistent claims (optional) |
| `PROJECT_NAME` | `Claimflow Autopilot` | Display name in API docs |

See [`.env.example`](../.env.example) for the full list.

---

## 3. Run Backend + Frontend

Use **two terminals**:

```bash
# Terminal 1 — Backend (FastAPI on :8000)
make run
```

```bash
# Terminal 2 — Frontend (Streamlit on :8501)
make run-frontend
```

### Verify

| URL | Purpose |
|-----|---------|
| http://localhost:8000/api/v1/docs | Swagger API docs |
| http://localhost:8000/api/v1/health | Health + Alibaba Cloud status |
| http://localhost:8501 | Streamlit dashboard |

```bash
curl http://localhost:8000/api/v1/health | jq
```

---

## 4. Storage Backends (Local vs OSS)

Claimflow uses the **Strategy Pattern** — switch backends via `STORAGE_BACKEND`:

### Local (default — development)

```bash
STORAGE_BACKEND=local
LOCAL_UPLOAD_DIR=./uploads
LOCAL_UPLOAD_BASE_URL=http://localhost:8000
```

Files are saved to `./uploads/` and served at `http://localhost:8000/uploads/`.

### Alibaba Cloud OSS (production)

```bash
STORAGE_BACKEND=oss
OSS_BUCKET_NAME=your-bucket
OSS_ENDPOINT=https://oss-cn-hangzhou.aliyuncs.com
OSS_REGION=cn-hangzhou
OSS_OBJECT_PREFIX=claims/
```

Requires valid `ALIBABA_CLOUD_ACCESS_KEY_ID` and `ALIBABA_CLOUD_ACCESS_KEY_SECRET` with OSS permissions on the bucket.

> Restart the backend after changing `STORAGE_BACKEND`.

---

## 5. MockLLM — When It Activates

**MockLLM** is an offline fallback that returns deterministic structured responses when live Qwen models are unavailable. There is no separate toggle — it activates automatically.

### MockLLM is used when:

1. **ChatTongyi initialization fails** (invalid config at startup)
2. **All models in the fallback chain fail** — e.g. `qwen-max` → `qwen-plus` → `qwen-turbo` all return 403, timeout, or access-denied errors
3. **Qwen-VL vision models fail** — returns mock vision analysis with intentional text↔image inconsistency

### Use live Qwen (recommended for demos)

1. Set a valid `DASHSCOPE_API_KEY` in `.env`
2. Ensure models (`qwen-max`, `qwen-vl-max`) are **purchased/enabled** in the [DashScope console](https://dashscope.console.aliyun.com/)
3. Restart the backend
4. Confirm via health check: `alibaba_cloud_services.qwen_cloud.status` should be `"connected"`

### Recognise MockLLM in logs

```
WARNING  All DashScope models unavailable; using MockLLM offline fallback
```

MockLLM outputs simulate a **high-fraud scenario** (fraud score ~0.88) — useful for offline development but may confuse live demos if DashScope credentials are misconfigured.

---

## 6. Makefile Quick Reference

| Command | Description |
|---------|-------------|
| `make install` | Create venv and install dependencies |
| `make run` | Start FastAPI backend |
| `make run-frontend` | Start Streamlit dashboard |
| `make test` | Run pytest suite |
| `make lint` | Run ruff linter |
| `make clean` | Remove venv and build artifacts |

---

## 7. Optional: PostgreSQL

For persistent claim storage and LangGraph checkpointing:

```bash
DATABASE_URL=postgresql://claimflow:claimflow@localhost:5432/claimflow
```

Without `DATABASE_URL`, claims are stored in-memory and lost on server restart.

---

## Related Docs

- [Architecture](architecture.md)
- [Alibaba Cloud Proof](ALIBABA_CLOUD_PROOF.md)
- [README](../README.md)
