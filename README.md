<div align="center">

# braindump 🧠

> AI 时代的个人原材料库 — voice-first, AI-native, agent-ready

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Stars](https://img.shields.io/github/stars/ApeCodeAI/braindump?style=social)](https://github.com/ApeCodeAI/braindump/stargazers)

</div>

**braindump** 是一个开源的个人 dump 工具。通过 Telegram Bot、Web UI 或 CLI 随手记录想法、语音、图片、链接，AI 自动转写和摘要，任何 Agent 都可以通过 CLI 直接调用。

[中文](#中文) · [English](#english)

<!-- ![braindump UI](docs/screenshot.png) -->

---

## 中文

### Why braindump?

不是"另一个笔记工具"。braindump 解决的问题是：

- 🎙️ **Voice-first** — 走路、开车、散步时的灵感，语音 dump，本地 Whisper 自动转写
- 🤖 **AI-native** — 数据格式是 YAML + Markdown，AI 直接读；Agent 通过 CLI 直接调用
- 🔒 **Data ownership** — 每条记录是一个本地文件夹，你完全拥有数据
- 🧩 **Agent-ready** — 不只是你往里 dump，你的 AI 助手也能帮你沉淀知识
- ♻️ **数据永久保留，代码随时可换** — 文件即真相，SQLite 只是索引，可随时重建

### vs Flomo / Apple Notes / Obsidian

|                    | braindump          | Flomo     | Apple Notes | Obsidian    |
| ------------------ | ------------------ | --------- | ----------- | ----------- |
| 语音转写            | ✅ 本地 Whisper      | ❌        | ❌           | ❌          |
| AI 摘要             | ✅                  | ❌        | ❌           | (插件)       |
| Agent 可调用 (CLI)  | ✅                  | ❌        | ❌           | ❌          |
| 自部署              | ✅                  | ❌        | ❌           | ✅          |
| 数据格式            | YAML + Markdown    | 私有 DB   | 私有         | Markdown    |
| 开源                | ✅ Apache 2.0       | ❌        | ❌           | ❌          |

### Quick Start

#### 1. 安装

```bash
git clone https://github.com/ApeCodeAI/braindump.git
cd braindump
uv sync --extra transcribe
```

#### 2. 配置

```bash
mkdir -p ~/braindump-data
cp config.example.toml ~/braindump-data/config.toml
# 编辑 ~/braindump-data/config.toml，填入 Telegram api_id / api_hash / bot_token
```

api_id / api_hash 在 <https://my.telegram.org> 申请；bot_token 找 [@BotFather](https://t.me/BotFather)。

#### 3. 构建前端

```bash
cd frontend && npm install && npm run build && cd ..
```

#### 4. 运行

```bash
uv run braindump serve   # bot + web + 转写一起启动
```

- 🤖 给你的 Telegram Bot 发消息（文字 / 语音 / 图片 / 链接）
- 🌐 打开 <http://localhost:8080> 浏览
- 💻 命令行：`uv run braindump add "你的想法"`

#### Docker（一行启动）

```bash
mkdir -p ~/braindump-data
cp config.example.toml ~/braindump-data/config.toml
# 编辑 config.toml
docker compose up -d
```

### CLI（AI-first）

CLI 默认输出 JSON（给 Agent 解析用），加 `--human` 给人看。

```bash
# 记录
braindump add "今天的想法"
braindump add --type bookmark --bookmark-url "https://..." "my notes"
braindump add --audio voice.opus --tag "语音"
echo "piped content" | braindump add -
braindump add --file notes.md --tag "笔记"

# 检索
braindump list --today --human
braindump search "Agent"
braindump get <id> --content    # 纯文本，方便 pipe 给 LLM

# 管理
braindump update <id> --tag "AI"
braindump delete <id>
braindump stats
braindump tags

# AI 摘要
braindump summarize <id>
braindump summarize --all
```

完整 CLI 文档见 [skill/SKILL.md](skill/SKILL.md)。

### Agent 集成

任何 AI Agent（Claude Code / Codex / 自定义 Agent）都可以通过 CLI 使用 braindump：

```bash
# Agent 沉淀一次讨论的结论
braindump add --tag "讨论" "核心观点：Agent 需要长期记忆"

# Agent 检索用户今天的想法
braindump list --today | jq '.items[].content'

# Agent 搜索相关上下文
braindump search "产品想法" | jq -r '.items[].content'

# Pipe 给 LLM 做主题归纳
braindump search "AI" | jq -r '.items[].content' | llm "总结共同主题"
```

仓库包含 `skill/SKILL.md`，支持 skill discovery 的 Agent 框架可以自动发现使用方式。

### 数据结构

```
~/braindump-data/
  config.toml                        # 配置
  items/                             # 所有原始数据（唯一重要的目录）
    20260619-143052-a3f8/            # 每条记录 = 一个目录
      item.yaml                      # 元数据（type / tags / 时间戳）
      content.md                     # 内容（Markdown）
      audio.opus                     # 语音（可选）
      images/001.jpg                 # 图片（可选）
  braindump.db                       # SQLite 索引，可从 items/ 重建
  braindump_bot.session              # Telegram Bot session
```

**数据永久保留，代码随时可换。** 你可以重写整个 codebase —— items/ 不会动。

```bash
uv run braindump rebuild-index   # 从 items/ 重建 SQLite 索引
```

### 技术栈

- **Backend:** Python 3.12+ / FastAPI / SQLite (索引) / Pyrofork (Telegram MTProto)
- **转写:** faster-whisper (本地，可选 GPU)
- **AI:** OpenAI-compatible API (Kimi K2.5 / GPT / Claude)，可选
- **Frontend:** React 19 / Vite / Tailwind CSS v4 / shadcn/ui

### 配置说明

全部可配置项见 [config.example.toml](config.example.toml)。

| Section       | 说明                                                       |
| ------------- | ---------------------------------------------------------- |
| `[telegram]`  | Bot 凭证 + 允许的用户 ID 白名单                              |
| `[transcribe]`| Whisper 模型大小（`tiny` / `base` / `small` / `medium` / `large-v3`） |
| `[web]`       | Web 监听地址和端口                                          |
| `[llm]`       | AI 摘要（OpenAI-compatible，默认关闭）                       |

环境变量：

- `BRAINDUMP_DATA_DIR` — 覆盖数据目录（默认 `~/braindump-data`）
- `MOONSHOT_API_KEY` / `OPENAI_API_KEY` — LLM provider 凭证

### 测试

```bash
uv run pytest tests/ -v
```

### 贡献

欢迎 issue 和 PR。请遵守 [Apache 2.0](LICENSE)。

---

## English

**braindump** is an open-source personal dump tool. Capture thoughts, voice memos, images, and bookmarks through Telegram, the Web UI, or the CLI. Voice messages are transcribed locally with Whisper. Every AI agent can read and write through a clean JSON CLI.

### Why?

This is not yet another note-taking app. braindump exists for a different reason:

- **Voice-first** — capture ideas while walking, driving, or cooking; local Whisper transcribes them.
- **AI-native** — data is stored as YAML + Markdown files. AI can read it directly. Agents call the CLI directly.
- **Data ownership** — every item is a self-contained folder on your disk. Nothing is locked behind a vendor.
- **Agent-ready** — your AI assistants can dump into your second brain, not just you.
- **Forever data, replaceable code** — files are the source of truth, SQLite is a rebuildable index.

### Quick Start

```bash
# 1. Install
git clone https://github.com/ApeCodeAI/braindump.git
cd braindump
uv sync --extra transcribe

# 2. Configure
mkdir -p ~/braindump-data
cp config.example.toml ~/braindump-data/config.toml
# Edit ~/braindump-data/config.toml with Telegram credentials
# Get api_id/api_hash at https://my.telegram.org
# Get bot_token from @BotFather

# 3. Build frontend
cd frontend && npm install && npm run build && cd ..

# 4. Run
uv run braindump serve
```

Open <http://localhost:8080>, message your Telegram bot, or use the CLI directly.

#### Docker

```bash
mkdir -p ~/braindump-data
cp config.example.toml ~/braindump-data/config.toml
# edit config.toml
docker compose up -d
```

### CLI (AI-first)

Default output is JSON for agents. Add `--human` for readable output.

```bash
braindump add "your thought"
braindump add --type bookmark --bookmark-url "https://..." "commentary"
braindump add --audio voice.opus --tag voice
echo "piped" | braindump add -

braindump list --today --human
braindump search "Agent"
braindump get <id> --content     # raw text, pipe to LLM

braindump update <id> --tag AI
braindump stats
braindump tags
braindump summarize <id>
```

See [skill/SKILL.md](skill/SKILL.md) for the full agent-facing reference.

### Data Structure

```
~/braindump-data/items/
  20260619-143052-a3f8/   # one directory per item
    item.yaml             # metadata (type, tags, timestamps)
    content.md            # the actual content
    audio.opus            # voice recording (optional)
    images/001.jpg        # photos (optional)
```

**Data is permanent. Code is temporary.** You can rewrite the entire codebase and your items survive untouched. Rebuild the index any time:

```bash
uv run braindump rebuild-index
```

### Tech Stack

- **Backend:** Python 3.12+, FastAPI, SQLite, Pyrofork (Telegram MTProto)
- **Transcription:** faster-whisper (local, optional GPU)
- **AI:** OpenAI-compatible APIs (optional, off by default)
- **Frontend:** React 19, Vite, Tailwind v4, shadcn/ui

### Configuration

See [config.example.toml](config.example.toml) for all options.

Environment variables:

- `BRAINDUMP_DATA_DIR` — override the data directory (default `~/braindump-data`)
- `MOONSHOT_API_KEY` / `OPENAI_API_KEY` — LLM provider credentials

### Tests

```bash
uv run pytest tests/ -v
```

### License

Apache License 2.0 — see [LICENSE](LICENSE).
