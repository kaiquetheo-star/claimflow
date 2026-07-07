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

## 5. 🎭 Demo Mode vs Production Mode

Claimflow uses a **feature-flag pattern** common in enterprise AI systems: the same pipeline runs in both modes; only the inference backend changes.

| Mode | `USE_MOCK_LLM` | AI Inference | Use case |
|------|----------------|--------------|----------|
| **Demo / hackathon** | `true` | MockLLM (deterministic scenarios) | Consistent video demos, offline testing |
| **Production** | `false` | Live Qwen Cloud via DashScope | Real-world claim processing |

### What MockLLM provides

MockLLM returns **three deterministic scenarios** selected by keywords in the claim text:

| Scenario | Trigger keywords | Expected outcome |
|----------|------------------|------------------|
| **STORM** (legitimate) | `tempestade`, `chuva`, `vendaval`, `vento` | Auto-approved (~0.15 risk) |
| **FRAUD** (obvious) | `fogo`, `incêndio`, `queimou` | Human review → reject (~0.88 risk) |
| **AMBIGUOUS** (default) | No keyword match | Human review (~0.65 risk) |

This ensures every demo run produces predictable, realistic results — no random LLM variance.

### Real DashScope connectivity is still proven

Even in demo mode, the `/api/v1/health` endpoint probes the real DashScope API (`GET /models` → HTTP 200). The startup banner confirms:

```
║ Real DashScope API: ✅ CONNECTED (health check passed) ║
║ AI Inference: 🎭 MockLLM (deterministic scenarios)        ║
```

This demonstrates that Alibaba Cloud integration is live; only inference is routed through the feature flag.

### Switch to production

Change **one environment variable** and restart the backend:

```bash
USE_MOCK_LLM=false
```

No code changes required. The LangGraph pipeline, vision service, weather tools, and human-in-the-loop routing remain identical.

### MockLLM offline fallback (automatic)

MockLLM also activates automatically when DashScope models are unavailable (no feature flag needed):

1. **ChatTongyi initialization fails** (invalid config at startup)
2. **All models in the fallback chain fail** — e.g. 403, timeout, access-denied
3. **Qwen-VL vision models fail** — returns mock vision analysis

Recognise automatic fallback in logs:

```
WARNING  All DashScope models unavailable; using MockLLM offline fallback
🎭 MockLLM: Detected scenario FRAUD_CLAIM (keyword: 'fogo')
```

---

## 6. MockLLM — Legacy Reference

_See section 5 above for the full demo vs production guide._

When `USE_MOCK_LLM` is not set, MockLLM still serves as the last-resort fallback in the model chain (`qwen-max` → `qwen-plus` → `qwen-turbo` → MockLLM).

---

## 7. Makefile Quick Reference

| Command | Description |
|---------|-------------|
| `make install` | Create venv and install dependencies |
| `make run` | Start FastAPI backend |
| `make run-frontend` | Start Streamlit dashboard |
| `make test` | Run pytest suite |
| `make lint` | Run ruff linter |
| `make clean` | Remove venv and build artifacts |

---

## 8. Optional: PostgreSQL

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
