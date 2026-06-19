# braindump v2

Personal dump tool — Telegram Bot + Web UI for capturing thoughts, voice, images, links.

**Core principle: data is forever, code is replaceable.**

See [DESIGN.md](DESIGN.md) for full specification.

## Quick start

```bash
# Install
uv sync --extra transcribe

# Configure (copy and edit)
mkdir -p ~/braindump-data
cp config.example.toml ~/braindump-data/config.toml
# edit ~/braindump-data/config.toml with your Telegram credentials

# Build frontend
cd frontend && npm install && npm run build && cd ..

# Run (bot + web + transcriber together)
uv run braindump serve

# Web only
uv run braindump web

# Rebuild SQLite index from items/
uv run braindump rebuild-index
```

Web UI: http://localhost:8080
