# braindump 🧠

> 个人表达的原材料库。把脑子里的东西 dump 出来。

通过 Telegram Bot 统一输入文字、图片、视频、语音，自动转写音视频为文字，Web UI 浏览回顾。

与 Flomo/Memos 的区别：这不是通用笔记工具，而是专注于**有意识的个人表达**——视频想法、语音思考、文字观点。Telegram Bot 就是过滤器：你主动发给它的 = 值得记录的表达。

## Features

### ✅ v0.1.0 已实现

- **Telegram Bot 接收** — 文字、图片、视频、语音、文件，全部自动保存
  - Pyrofork MTProto 协议，支持 **2GB** 大文件下载
  - 需要 `api_id` + `api_hash`（从 [my.telegram.org](https://my.telegram.org) 免费获取）
  - 用户白名单，只接受指定用户的消息
  - 转发消息保留原始发送者和时间
  - `#标签` 自动提取
  - Bot 命令：`/start` `/stats` `/recent` `/status`
- **自动转写** — 语音和视频自动转为文字
  - [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 引擎，CPU/GPU 均可
  - 模型可选：`tiny` / `base` / `small` / `medium` / `large-v3`
  - 异步队列处理，不阻塞 Bot 响应
- **Web UI** — 时间线浏览你的所有表达
  - 按日期分组的时间线
  - 全文搜索（SQLite FTS5）
  - 按类型筛选（文字/图片/视频/语音）
  - 标签筛选
  - Markdown 渲染，链接可点击
  - 响应式设计，手机友好
  - 可选 token 认证保护
- **Flomo 导入** — 从 Flomo 导出的 HTML 批量导入
  - 保留原始时间、标签、图片
  - 自动去重
- **数据安全**
  - **文件即真相**：所有原始文件按 `YYYY/MM/DD` 存储在文件系统中
  - **数据库是索引**：SQLite 丢了可从文件重建（`rebuild-index` 命令）
  - 文字笔记也存为 `.md` 文件
  - 软删除（移到 trash/，可恢复）
  - `rebuild-index` 前自动备份数据库
- **Docker 部署** — 一行命令启动全部服务

### 🔜 下一步

- [ ] UI 精细打磨
- [ ] 简单认证（Web UI 密码保护）
- [ ] 更多导入源（Day One、Apple Notes...）
- [ ] GPU 加速转写
- [ ] 内容导出（Markdown/JSON）

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

# 导入 Flomo（可选）
uv run python -m braindump import flomo /path/to/flomo-export/

# 运行
uv run python -m braindump serve    # 全部启动（Bot + Web + 转写）
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

# 启动
docker compose up -d

# 查看日志
docker compose logs -f

# 导入 Flomo（可选）
docker compose exec braindump uv run python -m braindump import flomo /data/flomo-export/
```

Docker 镜像特点：
- 包含 `ffmpeg` 处理音视频
- Whisper 模型首次启动时自动下载到 data volume（不打进镜像）
- `/data` volume 持久化所有数据（配置、数据库、媒体文件、模型缓存）

迁移已有数据：`cp -r ~/braindump-data/* ./data/`

## Configuration

```toml
[general]
data_dir = "~/braindump-data"
timezone = "Asia/Shanghai"
day_boundary_hour = 4              # 凌晨 4 点前的内容算前一天

[telegram]
api_id = 12345                     # https://my.telegram.org 获取
api_hash = "your_api_hash"
bot_token = "your_bot_token"       # @BotFather 获取
allowed_users = [123456789]        # 你的 Telegram user ID

[transcribe]
engine = "whisper"                 # whisper | funasr
whisper_model = "small"            # tiny | base | small | medium | large-v3
whisper_device = "cpu"             # cpu | cuda

[web]
host = "127.0.0.1"
port = 8080
# secret_key = "your_secret"      # 启用 token 认证
```

## Data Directory

```
~/braindump-data/
├── config.toml                # 配置文件
├── braindump.db               # SQLite 索引（可重建）
├── backup/                    # 自动备份
└── media/                     # 原始文件（真正的数据）
    ├── text/2026/03/12/       # 文字笔记 (.md)
    ├── image/2026/03/12/      # 图片
    ├── video/2026/03/12/      # 视频
    └── audio/2026/03/12/      # 语音
```

## Tech Stack

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.11+ / uv |
| Telegram | Pyrofork (MTProto, ≤2GB 文件) |
| Web | FastAPI + Jinja2 |
| 转写 | faster-whisper (CPU/GPU) |
| 数据库 | SQLite + aiosqlite + FTS5 |
| 部署 | Docker / docker-compose |

## License

MIT
