<div align="center">

# ThinkTape 🎙️

> Voice & Video First 的个人思维录音带 — AI-native, Agent-ready, Open Source

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![Stars](https://img.shields.io/github/stars/ApeCodeAI/thinktape?style=social)](https://github.com/ApeCodeAI/thinktape/stargazers)
[![Sponsored by BytePass](https://img.shields.io/badge/sponsored%20by-BytePass.ai-7C3AED.svg)](https://bytepass.ai)

Built by **[ApeCode.ai](https://apecode.ai)** · Sponsored by **[BytePass.ai](https://bytepass.ai)**

</div>

**ThinkTape** 是一个 Voice & Video First 的开源个人思维录音带。语音和视频是第一输入方式——走路、开车、散步时随手说，本地 Whisper 自动转写。文字、图片、链接也支持。AI 自动摘要，任何 Agent 通过 CLI 直接调用。



[中文](#中文) · [English](#english)

<!-- ![ThinkTape UI](docs/screenshot.png) -->

---

## 中文

### Why ThinkTape?

不是"另一个笔记工具"。ThinkTape 解决的问题是：

- 🎙️ **Voice & Video First** — 语音和视频是第一输入方式。走路、开车、散步时随手说，本地 Whisper 自动转写；原始媒体以只读、校验和验证的不可变资产保存
- 🤖 **AI-native** — SQLite 保存规范内容与元数据；Agent 通过 JSON CLI 直接调用
- 🔗 **[[双链]]** — 支持 `[[wikilink]]`，在碎片之间建立关联
- 🔒 **Local-first** — SQLite 数据库和不可变媒体资产都保存在你自己的数据目录
- 🧩 **Agent-ready** — 不只是你往里 dump，你的 AI 助手也能帮你沉淀知识
- ♻️ **数据永久保留，代码随时可换** — SQLite 是内容真相，媒体资产不可变；搜索、标签和链接索引可随时重建

### vs Flomo / Apple Notes / Obsidian

|                    | ThinkTape          | Flomo     | Apple Notes | Obsidian    |
| ------------------ | ------------------ | --------- | ----------- | ----------- |
| 语音/视频转写        | ✅ 本地 Whisper 无限制 | ⚠️ 仅 1 分钟 | ❌           | ❌          |
| AI 摘要             | ✅                  | ❌        | ❌           | (插件)       |
| [[双链]]           | ✅                  | ❌        | ❌           | ✅          |
| Agent 可调用 (CLI)  | ✅                  | ❌        | ❌           | ❌          |
| 本地数据所有权       | ✅ SQLite + 媒体资产 | 私有 DB   | 私有         | ✅ Markdown |
| 开源                | ✅ Apache 2.0       | ❌        | ❌           | ❌          |

### Quick Start

#### 1. 安装

```bash
git clone https://github.com/ApeCodeAI/thinktape.git
cd thinktape
uv sync --extra transcribe
```

#### 2. 配置

```bash
mkdir -p ~/thinktape-data
cp config.example.toml ~/thinktape-data/config.toml
# 编辑 ~/thinktape-data/config.toml，填入 Telegram api_id / api_hash / bot_token
```

api_id / api_hash 在 <https://my.telegram.org> 申请；bot_token 找 [@BotFather](https://t.me/BotFather)。

#### 3. 构建前端

```bash
cd frontend && npm install && npm run build && cd ..
```

#### 4. 运行

```bash
uv run thinktape serve   # bot + web + 转写一起启动
```

- 🤖 给你的 Telegram Bot 发消息（文字 / 语音 / 图片 / 链接）
- 🌐 打开 <http://localhost:8080> 浏览
- 💻 命令行：`uv run thinktape add "你的想法"`

#### Docker（一行启动）

```bash
mkdir -p ~/thinktape-data
cp config.example.toml ~/thinktape-data/config.toml
# 编辑 config.toml
docker compose up -d
```

### CLI（AI-first）

CLI 默认输出 JSON（给 Agent 解析用），加 `--human` 给人看。

```bash
# 记录
thinktape add "今天的想法"
thinktape add --type bookmark --bookmark-url "https://..." "my notes"
thinktape add --audio voice.opus --tag "语音"
echo "piped content" | thinktape add -
thinktape add --file notes.md --tag "笔记"

# 检索
thinktape list --today --human
thinktape search "Agent"
thinktape get <id> --content    # 纯文本，方便 pipe 给 LLM

# 管理
thinktape update <id> --tag "AI"
thinktape delete <id>
thinktape stats
thinktape tags

# AI 摘要
thinktape summarize <id>
thinktape summarize --all
```

完整 CLI 文档见 [skill/SKILL.md](skill/SKILL.md)。

### Agent 集成

任何 AI Agent（Claude Code / Codex / 自定义 Agent）都可以通过 CLI 使用 ThinkTape：

```bash
# Agent 沉淀一次讨论的结论
thinktape add --tag "讨论" "核心观点：Agent 需要长期记忆"

# Agent 检索用户今天的想法
thinktape list --today | jq '.items[].content'

# Agent 搜索相关上下文
thinktape search "产品想法" | jq -r '.items[].content'

# Pipe 给 LLM 做主题归纳
thinktape search "AI" | jq -r '.items[].content' | llm "总结共同主题"
```

仓库包含 `skill/SKILL.md`，支持 skill discovery 的 Agent 框架可以自动发现使用方式。

### 数据结构

```
~/thinktape-data/
  config.toml                        # 配置
  thinktape.db                       # 规范内容、元数据、资产记录及存储契约标记
  assets/                            # 应用只读的不可变媒体
    20260619-143052-a3f8/
      audio.opus                     # 语音（可选，读取前校验 SHA-256）
      001.jpg                        # 图片（可选，读取前校验 SHA-256）
  items/                             # 仅旧版本迁移输入；正常运行不读写
  thinktape_bot.session              # Telegram Bot session
```

旧版 `items/` 数据必须显式迁移。先执行只读检查，再应用迁移；存在问题时命令返回非零，正常启动也会拒绝未完成迁移的旧存储。

```bash
uv run thinktape migrate-legacy --dry-run
uv run thinktape migrate-legacy --apply
uv run thinktape rebuild-index   # 仅从 SQLite 重建 FTS/标签/链接派生索引
```

### 技术栈

- **Backend:** Python 3.12+ / FastAPI / SQLite（规范存储）/ Pyrofork (Telegram MTProto)
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

- `THINKTAPE_DATA_DIR` — 覆盖数据目录（默认 `~/thinktape-data`）
- `MOONSHOT_API_KEY` / `OPENAI_API_KEY` — LLM provider 凭证

### 测试

```bash
uv run pytest tests/ -v
```

### 贡献

欢迎 issue 和 PR。请遵守 [Apache 2.0](LICENSE)。

---

## English

**ThinkTape** is a Voice & Video First open-source personal think tape. Voice and video are the primary input — capture ideas while walking, driving, or cooking; local Whisper transcribes automatically. Text, images, and links are also supported. Any AI agent can read and write through a clean JSON CLI.

Part of the [ApeCode.ai](https://apecode.ai) open source ecosystem, sponsored by [BytePass.ai](https://bytepass.ai).

### Why?

This is not yet another note-taking app. ThinkTape exists for a different reason:

- **Voice & Video First** — voice and video are the primary input. Capture ideas while walking, driving, or cooking; local Whisper transcribes automatically. Original media files preserved forever.
- **AI-native** — canonical content and metadata live in SQLite; agents use the JSON CLI directly.
- **[[Bi-directional Links]]** — `[[wikilinks]]` connect fragments into a knowledge graph.
- **Local-first** — the SQLite database and immutable media assets remain in your own data directory.
- **Agent-ready** — your AI assistants can capture and retrieve material through the CLI.
- **Forever data, replaceable code** — SQLite is canonical, media assets are immutable, and derived search/tag/link indexes are rebuildable.

### Quick Start

```bash
# 1. Install
git clone https://github.com/ApeCodeAI/thinktape.git
cd thinktape
uv sync --extra transcribe

# 2. Configure
mkdir -p ~/thinktape-data
cp config.example.toml ~/thinktape-data/config.toml
# Edit ~/thinktape-data/config.toml with Telegram credentials
# Get api_id/api_hash at https://my.telegram.org
# Get bot_token from @BotFather

# 3. Build frontend
cd frontend && npm install && npm run build && cd ..

# 4. Run
uv run thinktape serve
```

Open <http://localhost:8080>, message your Telegram bot, or use the CLI directly.

#### Docker

```bash
mkdir -p ~/thinktape-data
cp config.example.toml ~/thinktape-data/config.toml
# edit config.toml
docker compose up -d
```

### CLI (AI-first)

Default output is JSON for agents. Add `--human` for readable output.

```bash
thinktape add "your thought"
thinktape add --type bookmark --bookmark-url "https://..." "commentary"
thinktape add --audio voice.opus --tag voice
echo "piped" | thinktape add -

thinktape list --today --human
thinktape search "Agent"
thinktape get <id> --content     # raw text, pipe to LLM

thinktape update <id> --tag AI
thinktape stats
thinktape tags
thinktape summarize <id>
```

See [skill/SKILL.md](skill/SKILL.md) for the full agent-facing reference.

### Data Structure

```
~/thinktape-data/
  thinktape.db                    # canonical content, metadata, asset records, storage marker
  assets/                         # application-read-only immutable media
    20260619-143052-a3f8/
      audio.opus                  # optional; SHA-256 verified before use
      001.jpg                     # optional; SHA-256 verified before use
  items/                          # legacy migration input only
```

Legacy `items/` storage requires an explicit migration. Inspect it without writes first, then apply. The command exits nonzero on issues, and normal startup rejects legacy or unmarked storage until migration succeeds.

```bash
uv run thinktape migrate-legacy --dry-run
uv run thinktape migrate-legacy --apply
uv run thinktape rebuild-index   # derived FTS/tag/link indexes only
```

### Tech Stack

- **Backend:** Python 3.12+, FastAPI, SQLite, Pyrofork (Telegram MTProto)
- **Transcription:** faster-whisper (local, optional GPU)
- **AI:** OpenAI-compatible APIs (optional, off by default)
- **Frontend:** React 19, Vite, Tailwind v4, shadcn/ui

### Configuration

See [config.example.toml](config.example.toml) for all options.

Environment variables:

- `THINKTAPE_DATA_DIR` — override the data directory (default `~/thinktape-data`)
- `MOONSHOT_API_KEY` / `OPENAI_API_KEY` — LLM provider credentials

### Tests

```bash
uv run pytest tests/ -v
```

### License

Apache License 2.0 — see [LICENSE](LICENSE).
