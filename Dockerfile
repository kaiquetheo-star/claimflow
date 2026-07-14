# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — builder: install Python dependencies into an isolated venv
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install .

# ---------------------------------------------------------------------------
# Stage 2 — runtime: lean image, non-root user, health check
# ---------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    LOCAL_UPLOAD_DIR=/app/uploads

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 claimflow \
    && useradd --uid 1000 --gid claimflow --home-dir /app --shell /usr/sbin/nologin claimflow \
    && mkdir -p /app/uploads \
    && chown -R claimflow:claimflow /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=claimflow:claimflow streamlit_app.py ./
COPY --chown=claimflow:claimflow alembic.ini ./
COPY --chown=claimflow:claimflow alembic ./alembic
COPY --chown=claimflow:claimflow docker/entrypoint.sh /app/entrypoint.sh

RUN chmod +x /app/entrypoint.sh

USER claimflow

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/health || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "claimflow.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
