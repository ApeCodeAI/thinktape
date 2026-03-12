FROM python:3.12-slim

# System deps for faster-whisper + pyrofork
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY braindump/ braindump/
COPY migrations/ migrations/
COPY README.md ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Data volume (config + db + media + whisper models)
VOLUME /data

# Expose web port
EXPOSE 8080

# Whisper model cache → /data/models (persistent, not baked into image)
ENV BRAINDUMP_DATA_DIR=/data
ENV HF_HOME=/data/models

# Default: run all services (Bot + Web + Transcribe)
CMD ["uv", "run", "python", "-m", "braindump", "serve"]
