# syntax=docker/dockerfile:1.7
# --- Builder: install dependencies into a venv --------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# --- Runtime: slim image, non-root user --------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    WORKSPACE_ROOT=/data/workspaces

# git is required at runtime by the DevOps/Builder agents for clone/commit/push.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system rimo \
    && useradd --system --gid rimo --create-home --home-dir /home/rimo rimo \
    && mkdir -p /data/workspaces \
    && chown -R rimo:rimo /data

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=rimo:rimo . .

USER rimo
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# The default command runs the API. The worker uses the same image with a
# different command (see docker-compose / k8s manifests).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
