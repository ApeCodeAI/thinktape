# braindump 🧠

> 个人表达的原材料库。把脑子里的东西 dump 出来。

通过 Telegram Bot 统一输入文字、图片、视频、语音，自动转写音视频为文字，Web UI 浏览回顾。

## Features

- **Telegram Bot** — 发消息即记录，支持文字/图片/视频/语音/文件
- **自动转写** — 语音和视频自动转为文字（faster-whisper CPU/GPU）
- **Web UI** — 时间线浏览、搜索、标签筛选、Markdown 渲染
- **Flomo 导入** — 从 Flomo 导出 HTML 批量导入历史笔记
- **文件即真相** — 所有文件存储在本地文件系统，数据库只是索引

## Quick Start

```bash
# Install
git clone https://github.com/ApeCodeAI/braindump.git
cd braindump
uv sync --extra bot

# Configure
mkdir -p ~/braindump-data
cp config.example.toml ~/braindump-data/config.toml
# Edit config.toml with your Telegram credentials

# Import Flomo (optional)
uv run python -m braindump import flomo /path/to/flomo-export/

# Run
uv run python -m braindump serve    # Bot + Web + Transcribe
uv run python -m braindump web      # Web UI only
uv run python -m braindump bot      # Telegram Bot only
```

## Configuration

```toml
[general]
data_dir = "~/braindump-data"
timezone = "Asia/Shanghai"
day_boundary_hour = 4

[telegram]
api_id = 12345                    # from https://my.telegram.org
api_hash = "your_api_hash"
bot_token = "your_bot_token"      # from @BotFather
allowed_users = [123456789]       # your Telegram user ID

[transcribe]
engine = "whisper"                # whisper or funasr
whisper_model = "small"           # tiny/base/small/medium/large
whisper_device = "cpu"            # cpu or cuda

[web]
host = "127.0.0.1"
port = 8080
```

## Data Directory

```
~/braindump-data/
├── config.toml
├── braindump.db              # SQLite index
└── media/
    ├── text/YYYY/MM/DD/      # Text notes as .md files
    ├── image/YYYY/MM/DD/     # Photos
    ├── video/YYYY/MM/DD/     # Videos
    └── audio/YYYY/MM/DD/     # Voice messages
```

## Tech Stack

- **Python 3.11+** with uv
- **Pyrofork** (MTProto) — Telegram Bot, supports files up to 2GB
- **FastAPI** + Jinja2 — Web UI
- **faster-whisper** — Speech-to-text (CPU/GPU)
- **SQLite** + aiosqlite — Metadata index

## License

MIT
