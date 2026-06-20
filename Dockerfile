# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build frontend ----------
FROM node:20-alpine AS frontend

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------- Stage 2: python runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    THINKTAPE_DATA_DIR=/data

# System deps:
# - build-essential: tgcrypto (Pyrofork) builds a C extension
# - ffmpeg, libsndfile1: faster-whisper audio decoding
# - ca-certificates: HTTPS to Telegram / LLM providers
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ffmpeg \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app

# Pre-install runtime deps for better layer caching (deps rarely change).
RUN uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python \
        "fastapi>=0.115.0" \
        "uvicorn[standard]>=0.32.0" \
        "aiosqlite>=0.20.0" \
        "pyrofork>=2.3.45" \
        "tgcrypto>=1.2.5" \
        "pyyaml>=6.0.2" \
        "pydantic>=2.9.0" \
        "python-multipart>=0.0.12" \
        "click>=8.1.7" \
        "httpx>=0.27.0" \
        "faster-whisper>=1.0.3"

# Copy source and built frontend
COPY pyproject.toml README.md ./
COPY thinktape/ ./thinktape/
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Install the package itself (no deps — already installed above)
RUN uv pip install --python /opt/venv/bin/python --no-deps .

# Data volume (items + config + sqlite + bot session)
VOLUME ["/data"]

EXPOSE 8080

# Default: run everything (bot + web + transcriber).
# Override at runtime, e.g. `docker run ... thinktape web` for web-only.
ENTRYPOINT ["thinktape"]
CMD ["serve"]
