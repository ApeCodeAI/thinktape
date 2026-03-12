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

# Pre-download whisper model (small, ~500MB) so first run is fast
RUN uv run python -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

# Data volume
VOLUME /data

# Expose web port
EXPOSE 8080

# Default: run all services (Bot + Web + Transcribe)
ENV BRAINDUMP_DATA_DIR=/data
CMD ["uv", "run", "python", "-m", "braindump", "serve"]
