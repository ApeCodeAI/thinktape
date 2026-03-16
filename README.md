# braindump 🧠

> 个人表达的原材料库。把脑子里的东西 dump 出来。

通过 Telegram Bot 统一输入文字、图片、视频、语音，自动转写音视频、自动生成 AI 摘要、把元数据写回 Markdown frontmatter，再用 Web UI 回看、搜索、回顾。

与 Flomo/Memos 的区别：这不是通用笔记工具，而是专注于**有意识的个人表达**——视频想法、语音思考、文字观点。Telegram Bot 就是过滤器：你主动发给它的，才会进入这个长期记忆库。

## 当前状态

- **版本**：`0.2.0`
- **形态**：Telegram Bot + FastAPI + React SPA
- **前端**：4 个页面 —— Timeline / Note Detail / Dashboard / Calendar
- **技术栈**：Vite + React 19 + TypeScript + Tailwind CSS v4 + shadcn/ui
- **测试**：仓库内目前有 `89` 个 pytest 用例（含单元、集成和 E2E）

## Features

### ✅ v0.1.0 基础能力

- **Telegram Bot 接收**
  - 文字、图片、视频、语音、文件，全部自动保存
  - Pyrofork MTProto 协议，支持 **2GB** 大文件下载
  - 需要 `api_id` + `api_hash`（从 [my.telegram.org](https://my.telegram.org) 免费获取）
  - 用户白名单，只接受指定用户的消息
  - 转发消息保留原始发送者和时间
  - `#标签` 自动提取
  - Bot 命令：`/start` `/stats` `/recent` `/status`
- **自动转写**
  - 语音和视频自动转为文字
  - [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 引擎，CPU / GPU 均可
  - 异步队列处理，不阻塞 Bot 响应
- **Web UI**
  - React SPA 浏览你的所有表达
  - 按日期分组的时间线（无限滚动）
  - 全文搜索（SQLite FTS5）
  - 按类型 / 标签筛选
  - Markdown 渲染 + 代码高亮 + KaTeX 数学公式
  - 统计仪表盘、日历热力图、暗色模式、响应式设计
  - 笔记创建、编辑、删除
  - 可选 token 认证保护
- **Flomo 导入**
  - 从 Flomo 导出的 HTML 批量导入
  - 保留原始时间、标签、图片
  - 自动去重
- **数据安全**
  - **文件即真相**：所有原始文件按 `YYYY/MM/DD` 存储在文件系统中
  - **数据库是索引**：SQLite 丢了可从文件重建（`rebuild-index`）
  - 文字笔记存为 `.md` 文件
  - 软删除（移到 `trash/`，可恢复）
  - `rebuild-index` 前自动备份数据库
- **Docker 部署**
  - 一行命令启动全部服务

### ✅ v0.2.0 新增能力

- **Phase 1：稳定性**
  - 全面改成 logging，基本告别到处散落的 `print`
  - 所有 bot handler 都加上 `safe_handler`，单条消息异常不再把整个 Bot 打穿
  - 用 `asyncio.TaskGroup` 统一管理 Web / Bot / 转写 / 摘要 / 回顾；任一组件崩溃会整体退出，交给 Docker 重启
  - 新增 `GET /health`，绕过鉴权直接返回 Bot、转写队列、摘要队列、每日回顾状态
  - 转写 / 摘要 worker 启动时会把卡在 `processing` 的任务重置回 `pending`
  - 视频转写前先用 `ffmpeg` 抽音轨，再喂给 whisper，质量和速度都更稳
  - Docker 内置 Python healthcheck，不依赖 `curl`
- **Phase 2a：AI 摘要**
  - 文字、语音、视频笔记支持自动 AI 摘要，默认用 Kimi K2.5，也兼容任意 OpenAI-compatible API
  - 独立 `SummaryWorker` 异步队列，与转写解耦，互不阻塞
  - 自动生成：`title`（15 字内）、`summary`（50–100 字）、`tags`、`mood`
  - 触发规则很明确：文字 ≥30 字直接进摘要队列；短文字 / 图片跳过；音频 / 视频等转写完成后再摘要
  - 提供 `braindump retry-summary`、`braindump summarize --backfill` 两个运维命令
  - JSON 解析会自动剥掉 markdown code fence，对 LLM 输出更宽容
- **Phase 2b：YAML Frontmatter**
  - 文字笔记 `.md` 文件现在带 YAML frontmatter
  - 已写回字段：`created`、`source`、`type`、`tags`、`title`、`summary`、`mood`
  - AI 摘要完成后会自动更新 frontmatter，而不只是写数据库
  - 提供 `braindump migrate-frontmatter` 给历史笔记补齐元数据
  - `rebuild-index` 会反向读取 frontmatter 回填数据库
  - FTS5 搜索已纳入 `ai_title` 和 `ai_summary`
- **Phase 3：大视频优化**
  - 下载过程中会给 Telegram 进度反馈：每 20% 更新一次，且至少间隔 3 秒，避免限流
  - 下载前先做磁盘空间检查：剩余空间小于文件大小的 1.5 倍会直接拒绝
  - 下载强制 30 分钟超时，并做好失败清理
- **Phase 4：Daily Review**
  - `ReviewScheduler` 每天通过 Telegram 随机推 3 条旧笔记，帮你把老内容重新翻出来
  - 用 `asyncio.sleep` 直接调度，不靠轮询刷数据库
  - `review_log` 持久化已发送记录，重启后也不会重复发
  - 可配置 `count`、`schedule`、`min_age_days`、`chat_id`

## Quick Start

### 本地运行

```bash
# 安装
git clone https://github.com/ApeCodeAI/braindump.git
cd braindump
uv sync

# 配置
mkdir -p ~/braindump-data
cp config.example.toml ~/braindump-data/config.toml
# 编辑 config.toml 填入你的 Telegram 凭证

# 可选：启用 AI 摘要（也可以改成任意 OpenAI-compatible 服务）
export MOONSHOT_API_KEY="your_api_key"

# 导入 Flomo（可选）
uv run python -m braindump import flomo /path/to/flomo-export/

# 运行
uv run python -m braindump serve    # 全部启动（Bot + Web + 转写 + 摘要 + Daily Review）
uv run python -m braindump web      # 仅 Web UI
uv run python -m braindump bot      # 仅 Telegram Bot
```

### Docker 部署

```bash
git clone https://github.com/ApeCodeAI/braindump.git
cd braindump

# 准备配置
mkdir -p data
cp config.example.toml data/config.toml
# 编辑 data/config.toml

# 启动（默认数据目录为 ./data）
docker compose up -d

# 或指定外部数据目录
BRAINDUMP_DATA_DIR=~/braindump-data docker compose up -d

# 查看日志
docker compose logs -f

# 导入 Flomo（可选）
docker compose exec braindump uv run python -m braindump import flomo /data/flomo-export/
```

Docker 镜像特点：
- 包含 `ffmpeg`，视频会先抽音轨再转写
- Whisper 模型首次启动时自动下载到 data volume（不打进镜像）
- 内置 `/health` + Docker healthcheck，镜像本身不需要 `curl`
- `/data` volume 持久化所有数据（配置、数据库、媒体文件、转写结果、备份、模型缓存）

如果你要在 Docker 里启用 AI 摘要，记得把 `MOONSHOT_API_KEY`（或者你在 `[llm].api_key_env` 里配置的变量名）一起注入到容器环境里。

迁移已有数据：`cp -r ~/braindump-data/* ./data/`（或者直接用 `BRAINDUMP_DATA_DIR=~/braindump-data` 指向已有目录）

## 常用命令

```bash
uv run python -m braindump rebuild-index
uv run python -m braindump retry-transcribe --all
uv run python -m braindump retry-summary --all
uv run python -m braindump summarize --backfill --min-length 50
uv run python -m braindump migrate-frontmatter
```

## Development

```bash
# Backend
uv run python -m braindump web      # http://localhost:8080

# Frontend（另开一个终端）
cd frontend && npm install && npm run dev   # http://localhost:5173（代理 API 到 :8080）

# E2E tests（需要前后端都已启动）
uv run python -m pytest tests/test_frontend_e2e.py -x -v
```

## Configuration

```toml
[general]
data_dir = "~/braindump-data"
timezone = "Asia/Shanghai"
day_boundary_hour = 4              # 凌晨 4 点前的内容算前一天

[telegram]
api_id = 12345                     # 从 https://my.telegram.org 获取
api_hash = "your_api_hash"
bot_token = "your_bot_token"      # 从 @BotFather 获取
allowed_users = [123456789]        # 你的 Telegram user ID

[transcribe]
engine = "whisper"                # whisper | funasr
whisper_model = "small"           # tiny | base | small | medium | large-v3
whisper_device = "cpu"            # cpu | cuda

[llm]
enabled = true
base_url = "https://api.moonshot.cn/v1"
model = "kimi-k2.5"
api_key_env = "MOONSHOT_API_KEY"  # 只从环境变量读取，不写进 config
timeout = 30
min_content_length = 30

[review]
enabled = true
count = 3
schedule = "09:00"                # 按 general.timezone 解释
min_age_days = 7
min_content_length = 20
chat_id = 123456789                # 可留空 / 设为 0，默认取 allowed_users[0]

[web]
host = "127.0.0.1"                # ⚠ 改成 0.0.0.0 前必须设置 secret_key
port = 8080
# secret_key = "your_secret"      # 暴露到网络时必填；/health 不受影响
```

补充说明：
- LLM API Key **只从环境变量读取**，这样不会混进 `config.toml`
- 如果 `enabled = true` 但没提供 API Key，服务会打一个 warning，然后自动禁用摘要，不会直接崩
- `GET /health` 默认绕过认证，适合本地探活和 Docker healthcheck
- 配了 `web.secret_key` 后，Web UI 支持简单 token 认证（query param / cookie）

## Data Directory

```text
~/braindump-data/
├── config.toml                # 配置文件
├── braindump.db               # SQLite 索引（可重建）
├── backup/                    # rebuild-index 前的自动备份
├── import/                    # 导入用临时目录 / 原始导入文件
├── media/                     # 原始文件（真正的数据）
│   ├── text/2026/03/12/       # 文字笔记（.md，含 YAML frontmatter）
│   ├── image/2026/03/12/      # 图片
│   ├── video/2026/03/12/      # 视频
│   └── audio/2026/03/12/      # 语音
└── transcripts/
    └── 2026/03/12/            # 音视频转写结果（.txt）
```

如果你用 Docker，模型缓存默认也会落到 `/data` volume 里。

## Tech Stack

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.11+ / uv |
| Telegram | Pyrofork（MTProto，≤2GB 文件） |
| Frontend | React 19 + TypeScript + Vite + Tailwind CSS v4 + shadcn/ui |
| Backend | FastAPI + aiosqlite |
| 转写 | faster-whisper + ffmpeg |
| AI 摘要 | OpenAI Python SDK + OpenAI-compatible API（默认 Kimi K2.5） |
| 搜索 | SQLite + FTS5（含 `ai_title` / `ai_summary`） |
| 部署 | Docker / docker-compose |

## 下一步

- [ ] UI 再打磨一轮，尤其是移动端时间线和详情页体验
- [ ] 更多导入源（Day One、Apple Notes...）
- [ ] GPU / 远程 ASR 的配置再做顺手一点
- [ ] 内容导出（Markdown / JSON / 备份包）
- [ ] 更聪明的检索与回顾（比如语义搜索、主题聚类）

## License

MIT
