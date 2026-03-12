# braindump — 设计文档

> **braindump** — 个人表达的原材料库。把脑子里的东西 dump 出来。
>
> 通过 Telegram 统一输入文字、图片、视频、语音，自动转写音视频为文字，Web UI 浏览回顾。
>
> 与 Flomo/Memos 的区别：这不是通用笔记工具，而是专注于**有意识的个人表达**——视频想法、语音思考、文字观点。Telegram Bot 就是过滤器：你主动发给它的 = 值得记录的表达。视频/语音转写是核心能力，让口头表达变成可搜索、可回顾的文字素材，未来可以成为博客、视频、播客的内容来源。

## 1. 核心原则

### 1.1 数据安全是底线

- **文件即真相**：所有原始文件（视频、图片、语音）按日期目录存储在文件系统中，永远可直接访问
- **数据库是索引，不是数据**：SQLite 只存元数据和转写文本。数据库丢了，文件还在；重建索引即可恢复
- **升级不破坏**：任何版本升级都不能删除或移动已有文件。数据库迁移必须有回滚脚本
- **人类可读**：目录结构和文件命名对人类友好，不依赖任何软件也能找到和使用文件
- **备份友好**：整个数据目录可直接 rsync/cp 备份，不需要特殊工具

### 1.2 简单优先

- 全 Python，最少依赖
- 个人使用，不考虑并发、权限、多用户
- 先跑起来，再优化

---

## 2. 技术栈

| 层 | 选型 | 版本要求 |
|---|------|---------|
| Telegram Bot | Pyrogram | ≥2.0 |
| 后端 API | FastAPI + Uvicorn | ≥0.100 |
| 数据库 | SQLite (aiosqlite) | Python 内置 |
| 转写（默认） | FunASR (Paraformer-large) | ≥1.0 |
| 转写（备选） | faster-whisper / 云端 API | — |
| 音频处理 | ffmpeg (系统安装) | ≥5.0 |
| 前端 | Jinja2 模板 + 原生 CSS/JS | — |
| Python 管理 | uv | ≥0.10 |

---

## 3. 文件系统设计（最重要）

### 3.1 目录结构

```
BRAINDUMP_DATA_DIR/                # 可配置的数据根目录，默认 ~/braindump-data
├── config.toml                    # 配置文件
├── braindump.db                   # SQLite 数据库（可重建）
├── braindump.db.bak               # 每次升级前自动备份
│
├── media/                         # 所有媒体文件
│   ├── video/
│   │   ├── 2026/
│   │   │   ├── 03/
│   │   │   │   ├── 20260312_103045_tg487.mp4        # 原始视频
│   │   │   │   ├── 20260312_103045_tg487.thumb.jpg  # 缩略图
│   │   │   │   └── 20260312_114523_tg489.mp4
│   │   │   └── 04/
│   │   └── 2025/                  # 导入的历史文件保持同样结构
│   │
│   ├── audio/                     # 语音消息
│   │   └── 2026/03/
│   │       └── 20260312_110000_tg490.ogg
│   │
│   └── image/                     # 图片
│       └── 2026/03/
│           └── 20260312_120000_tg492.jpg
│
├── transcripts/                   # 转写文本（独立存储，人类可读）
│   └── 2026/03/
│       ├── 20260312_103045_tg487.txt        # 纯文本转写
│       └── 20260312_103045_tg487.json       # 带时间戳的详细转写
│
├── import/                        # 导入数据的原始备份
│   ├── flomo/                     # Flomo 导出的原始 HTML
│   └── memos/                     # Memos 导出的原始数据
│
├── trash/                         # 软删除的文件暂存（purge 后才真正删除）
│   ├── 20260312_103045_tg487.mp4
│   └── 20260312_103045_tg487.txt
│
├── backup/                        # 数据库备份
│   ├── braindump_20260312_120000.db
│   └── braindump_20260315_120000.db
│
└── migrations/                    # 数据库迁移记录
    ├── 001_initial.sql
    └── 002_add_xxx.sql
```

### 3.2 文件命名规则

```
{YYYYMMDD}_{HHmmss}_{source}{id}.{ext}
```

- **时间**：内容的原始创建时间（不是文件系统时间）
- **归档规则**：凌晨 4 点前的内容，文件存入前一天的目录（可配置 `day_boundary_hour`）。例如 2026-03-13 02:30 录制的视频存入 `2026/03/12/`，但文件名中的时间仍为真实时间 `20260313_023000`
- **source**：来源标识
  - `tg` = Telegram
  - `fl` = Flomo 导入
  - `mm` = Memos 导入
  - `im` = 手动导入
- **id**：来源系统中的原始 ID（Telegram message_id 等）
- **ext**：保持原始扩展名

示例：
- `20260312_103045_tg487.mp4` — 2026-03-12 10:30:45 从 Telegram 收到的第 487 条消息
- `20250815_000000_fl1234.jpg` — 从 Flomo 导入的图片，原始 ID 1234

### 3.3 数据安全保证

**规则 1：文件写入后的删除必须经过两级确认**

**软删除（日常操作）：**
- Web UI 上点击删除 → 文件从 `media/` 移到 `trash/`，转写文件同步移动
- 数据库标记 `is_deleted = 1`
- Web UI 默认不显示已删除内容，但可以切换查看
- 随时可恢复（从 trash/ 移回 media/）

**物理删除（可选清理，不定期执行）：**
- CLI 命令 `python -m braindump purge --dry-run` 预览待删除内容
- `python -m braindump purge --confirm` 需要手动输入 "YES DELETE" 确认
- 执行前自动备份数据库
- 真正从文件系统删除 trash/ 中的文件

**规则 2：数据库可重建**

```bash
# 如果数据库损坏，可以从文件系统完整重建
python -m braindump rebuild-index
```

重建逻辑：
1. 扫描 `media/` 目录下所有文件
2. 从文件名解析时间和来源
3. 从 `transcripts/` 读取转写文本
4. 重新写入 SQLite

**规则 3：每次升级前自动备份数据库**

```bash
python -m braindump upgrade  # 自动执行: cp braindump.db backup/braindump_{timestamp}.db
```

### 3.4 转写文件说明

每个视频/语音生成两个转写文件：

**纯文本版 (.txt)**：人类直接可读
```
大家好，今天我想聊一下关于 Agent 落地的一些思考。
我认为现在的 Agent 最大的问题是...
```

**详细版 (.json)**：带时间戳，供程序使用
```json
{
  "source_file": "media/video/2026/03/12/20260312_103045_tg487.mp4",
  "model": "paraformer-zh",
  "language": "zh",
  "duration_seconds": 342,
  "transcribed_at": "2026-03-12T10:35:00+08:00",
  "segments": [
    {"start": 0.0, "end": 3.5, "text": "大家好，今天我想聊一下关于 Agent 落地的一些思考。"},
    {"start": 3.5, "end": 8.2, "text": "我认为现在的 Agent 最大的问题是..."}
  ]
}
```

---

## 4. 数据库设计

### 4.1 notes 表（核心）

```sql
CREATE TABLE notes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 内容
    content       TEXT,                     -- 文字内容（文字笔记的正文，或转写文本）
    media_type    TEXT NOT NULL DEFAULT 'text',  -- text / image / video / audio
    file_path     TEXT,                     -- 媒体文件相对路径（相对于 BRAINDUMP_DATA_DIR）
    thumbnail     TEXT,                     -- 缩略图相对路径
    transcript    TEXT,                     -- 转写/摘要文本（冗余存储，加速搜索）
    
    -- 时间
    created_at    TEXT NOT NULL,            -- 真实创建时间 ISO 8601（永远不改，UI 上原样显示）
    display_date  TEXT NOT NULL,            -- 归档日期 YYYY-MM-DD（凌晨 4 点前归入前一天，用于文件目录归档和 Web UI 时间线分组）
    imported_at   TEXT NOT NULL,            -- 导入/接收时间 ISO 8601
    
    -- 来源
    source        TEXT NOT NULL DEFAULT 'telegram',  -- telegram / flomo / memos / manual
    source_id     TEXT,                     -- 来源系统中的原始 ID
    
    -- 元数据
    tags          TEXT DEFAULT '',          -- 逗号分隔的标签
    duration      REAL,                     -- 音视频时长（秒）
    file_size     INTEGER,                  -- 文件大小（字节）
    
    -- 转发信息
    is_forwarded  INTEGER DEFAULT 0,        -- 是否为转发消息
    forward_from  TEXT,                     -- 原始发送者名称
    forward_date  TEXT,                     -- 原始发送时间 ISO 8601
    
    -- 状态
    is_deleted    INTEGER DEFAULT 0,        -- 软删除标记
    transcribe_status TEXT DEFAULT 'pending' -- pending / processing / done / failed / not_needed
);
```

### 4.2 attachments 表（多附件支持）

一条笔记可以有多个附件（如 Telegram media group 一次发多张图片）。

```sql
CREATE TABLE attachments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id    INTEGER NOT NULL REFERENCES notes(id),
    file_path  TEXT NOT NULL,              -- 媒体文件相对路径
    media_type TEXT NOT NULL,              -- image / video / audio
    thumbnail  TEXT,                       -- 缩略图路径（视频用）
    file_size  INTEGER,
    duration   REAL,                       -- 音视频时长（秒）
    sort_order INTEGER DEFAULT 0           -- 附件排序
);
```

**说明：** 单附件的笔记同样使用此表存储（sort_order = 0），notes 表的 `file_path`、`thumbnail`、`file_size`、`duration` 字段保留作为主附件的冗余快捷访问。

### 4.3 索引

```sql
-- 按时间浏览
CREATE INDEX idx_notes_created_at ON notes(created_at DESC);

-- 按来源筛选
CREATE INDEX idx_notes_source ON notes(source);

-- 按媒体类型筛选
CREATE INDEX idx_notes_media_type ON notes(media_type);

-- 全文搜索
CREATE VIRTUAL TABLE notes_fts USING fts5(
    content,
    transcript,
    tags,
    content='notes',
    content_rowid='id'
);
```

### 4.4 migrations 表（版本管理）

```sql
CREATE TABLE migrations (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
```

---

## 5. 配置文件

`config.toml`:

```toml
[general]
data_dir = "~/braindump-data"      # 数据根目录
timezone = "Asia/Shanghai"
day_boundary_hour = 4              # 日期分界线：凌晨 4 点前的内容算前一天

[telegram]
api_id = 12345678                   # 从 https://my.telegram.org 获取
api_hash = "your_api_hash"
bot_token = "your_bot_token"
allowed_users = [5439573095]        # 只接受这些用户的消息

[transcribe]
engine = "funasr"                   # funasr / whisper / api
# FunASR 配置（默认，中文效果最好，N97 跑得动）
funasr_model = "paraformer-zh"
# Whisper 配置（备选）
whisper_model = "medium"
whisper_device = "cpu"
# API 配置（备选，本地跑不动时用）
api_provider = "siliconflow"        # siliconflow / volcengine
api_key = ""

[web]
host = "0.0.0.0"
port = 8080
# secret_key = "xxx"               # 如果需要简单认证
```

---

## 6. 项目代码结构

```
braindump/                          # 项目代码仓库
├── pyproject.toml
├── README.md
│
├── braindump/
│   ├── __init__.py
│   ├── __main__.py                # CLI 入口: python -m braindump
│   ├── config.py                  # 配置加载
│   ├── database.py                # 数据库操作 + 迁移
│   │
│   ├── bot/                       # Telegram Bot
│   │   ├── __init__.py
│   │   └── handlers.py            # 消息处理（文字/图片/视频/语音）
│   │
│   ├── transcribe/                # 转写服务
│   │   ├── __init__.py
│   │   ├── engine.py              # 转写引擎统一接口
│   │   ├── funasr_engine.py       # FunASR Paraformer（默认）
│   │   ├── whisper_engine.py      # faster-whisper（备选）
│   │   └── api_engine.py          # 云端 API（备选）
│   │
│   ├── web/                       # Web UI（响应式，适配移动端）
│   │   ├── __init__.py
│   │   ├── app.py                 # FastAPI 应用
│   │   ├── routes.py              # API 路由
│   │   ├── templates/             # Jinja2 模板
│   │   │   ├── base.html
│   │   │   ├── timeline.html      # 时间线主页
│   │   │   └── note.html          # 单条笔记详情
│   │   └── static/                # CSS / JS
│   │       ├── style.css
│   │       └── app.js
│   │
│   └── importer/                  # 数据导入
│       ├── __init__.py
│       ├── flomo.py               # Flomo HTML 解析导入（V1）
│       └── files.py               # 本地文件批量导入
│
└── migrations/                    # SQL 迁移文件
    └── 001_initial.sql
```

---

## 7. 功能模块详细设计

### 7.1 Telegram Bot

**接收消息类型：**

| 消息类型 | 处理方式 |
|---------|---------|
| 纯文字 | 直接存为 text 类型笔记 |
| 图片 | 下载图片，存为 image 类型，caption 作为 content |
| 视频 | 下载视频，生成缩略图，排队转写 |
| 语音消息 | 下载 .ogg，排队转写 |
| 视频备注 (圆形视频) | 同视频处理 |
| 文件 (视频/音频) | 按类型处理 |
| 带 #tag 的文字 | 提取标签，存入 tags 字段 |
| 转发消息 | 记录原始发送者和时间，标记 is_forwarded=1，内容按原类型处理 |
| 多图消息 (media group) | 合并为一条笔记，多个附件存入 attachments 表 |

**Bot 命令：**

| 命令 | 功能 |
|------|------|
| /start | 欢迎消息 |
| /stats | 统计信息（总条数、各类型数量、存储占用） |
| /recent | 最近 5 条记录的摘要 |
| /status | 转写队列状态 |

**处理流程（以视频为例）：**

```
用户发送视频
  → Bot 收到 message
  → 验证 user_id 在 allowed_users 中
  → 下载视频到 media/video/YYYY/MM/DD/
  → 生成缩略图 (ffmpeg)
  → 写入数据库 (transcribe_status = 'pending')
  → 回复用户 "✅ 已保存，转写排队中"
  → 转写 worker 异步处理
    → ffmpeg 提取音轨
    → 转写引擎处理（默认 FunASR Paraformer）
    → 保存 .txt 和 .json 到 transcripts/
    → 更新数据库 transcript 字段和状态
    → 回复用户 "📝 转写完成：{前50字}..."
```

### 7.2 转写服务

**设计为异步队列**，避免阻塞 Bot 响应：

```python
import asyncio

class TranscribeWorker:
    def __init__(self, config):
        self.queue = asyncio.Queue()
        self.model = None  # 懒加载，首次转写时加载模型
    
    async def enqueue(self, note_id: int, file_path: str):
        await self.queue.put((note_id, file_path))
    
    async def run(self):
        while True:
            note_id, file_path = await self.queue.get()
            await self._transcribe(note_id, file_path)
    
    async def _transcribe(self, note_id, file_path):
        # 1. 提取音频（如果是视频）
        audio_path = await extract_audio(file_path)
        # 2. 根据配置选择引擎
        if self.engine == "funasr":
            result = self.funasr_model.generate(input=audio_path)
        elif self.engine == "whisper":
            result = self.whisper_model.transcribe(audio_path)
        else:
            result = await self.api_transcribe(audio_path)
        # 3. 保存转写文件
        save_transcript_files(result, file_path)
        # 4. 更新数据库
        await db.update_transcript(note_id, full_text, 'done')
```

**模型懒加载**：首次转写时才加载模型，节省内存。NAS 上内存可能有限。

**引擎选择说明：**
- **FunASR Paraformer-large**（默认）：中文效果最好，速度快（N97 上 10 分钟视频约 1-3 分钟），阿里达摩院专为中文优化
- **faster-whisper**（备选）：多语言通用，中文效果略逊于 Paraformer，速度较慢
- **云端 API**（备选）：本地跑不动时用，硅基流动约 ¥0.7/小时，火山引擎有免费额度

### 7.3 Web UI

**页面：**

**所有页面均做响应式适配，手机浏览器可正常使用。**

1. **时间线页（首页）** `/`
   - 按日期分组，最新在上
   - 每条笔记显示：时间、内容/转写摘要、缩略图、标签
   - 视频/语音可直接播放
   - 滚动加载更多（分页）
   - 顶部：简单搜索框 + 类型筛选（全部/文字/视频/语音/图片）

2. **笔记详情页** `/note/{id}`
   - 完整内容
   - 视频播放器 + 转写文字（带时间戳，点击跳转）
   - 语音播放器 + 转写文字
   - 图片查看
   - 标签编辑
   - 删除按钮（软删除，移到 trash/，需确认）
   - 已删除内容的恢复按钮

3. **统计页（可选）** `/stats`
   - 各类型数量、时间分布图表

**API 路由：**

```
GET  /                          # 时间线页面
GET  /note/{id}                 # 笔记详情页面
GET  /api/notes                 # 笔记列表 (JSON)
     ?page=1&size=20
     &type=video
     &tag=agent
     &q=搜索关键词
     &start=2026-01-01
     &end=2026-03-12
GET  /api/notes/{id}            # 单条笔记 (JSON)
DELETE /api/notes/{id}          # 软删除（移到 trash/）
POST /api/notes/{id}/restore    # 从 trash 恢复
GET  /media/{path}              # 静态媒体文件服务
```

### 7.4 数据导入

**Flomo 导入：**

```
1. 用户从 Flomo 导出 HTML 文件
2. 放入 BRAINDUMP_DATA_DIR/import/flomo/
3. 运行: python -m braindump import flomo
4. 解析 HTML，提取：
   - 内容（markdown）
   - 标签
   - 创建时间
   - 图片（如有）
5. 写入数据库，source='flomo'
6. 原始 HTML 保留在 import/flomo/ 不动
```

**Memos 导入（V2，暂不实现）：**

后续需要时再开发。

**本地文件批量导入：**

```
1. 将文件放入某个目录
2. 运行: python -m braindump import files /path/to/files --source manual
3. 从文件元数据读取原始时间（EXIF/媒体元数据）
4. 按命名规则复制到 media/ 目录
5. 视频/语音排队转写
```

---

## 8. CLI 命令

```bash
# 启动所有服务（Bot + Web + 转写 Worker）
python -m braindump serve

# 只启动 Web UI
python -m braindump web

# 只启动 Bot
python -m braindump bot

# 导入数据
python -m braindump import flomo /path/to/flomo/export
python -m braindump import files /path/to/files

# 数据库操作
python -m braindump rebuild-index    # 从文件系统重建数据库
python -m braindump upgrade          # 执行数据库迁移（自动备份）
python -m braindump backup           # 手动备份数据库

# 删除管理
python -m braindump purge --dry-run  # 预览 trash/ 中待清理的文件
python -m braindump purge --confirm  # 物理删除（需输入 YES DELETE 确认）
python -m braindump restore <id>     # 从 trash 恢复某条记录

# 工具
python -m braindump stats            # 显示统计信息
python -m braindump transcribe       # 手动触发待转写项目
```

---

## 9. 部署方式

### NAS 部署（推荐）

**目标硬件：极空间 Z4 Pro 标准版**
- CPU: Intel N97, 4核4线程, 3.6GHz
- 内存: 8GB DDR5
- 存储: 4TB SSD
- 运行方式: Docker

```bash
# 1. 克隆项目
git clone <repo> ~/braindump
cd ~/braindump

# 2. 安装依赖
uv sync

# 3. 安装 ffmpeg（如未安装）
# Synology: opkg install ffmpeg
# 或通过 Docker

# 4. 配置
cp config.example.toml ~/braindump-data/config.toml
# 编辑 config.toml 填入 Telegram 凭据

# 5. 启动
uv run python -m braindump serve

# 6. 设为开机自启（systemd 或 NAS 的任务计划）
```

### Docker 部署（可选）

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y ffmpeg
COPY . /app
WORKDIR /app
RUN pip install uv && uv sync
VOLUME /data
CMD ["uv", "run", "python", "-m", "braindump", "serve"]
```

```yaml
# docker-compose.yml
services:
  braindump:
    build: .
    volumes:
      - ~/braindump-data:/data
    ports:
      - "8080:8080"
    restart: unless-stopped
```

---

## 10. 升级策略

### 原则

1. **永远先备份数据库**
2. **文件系统只增不改**（新版本可以增加新目录，但不移动/重命名已有文件）
3. **数据库迁移必须可逆**（每个迁移有 up + down）

### 迁移文件格式

`migrations/002_add_summary.sql`:
```sql
-- up
ALTER TABLE notes ADD COLUMN summary TEXT;

-- down
-- SQLite 不支持 DROP COLUMN，所以 down 操作是重建表
-- 实际操作时通过 rebuild-index 重建
```

### 升级流程

```bash
git pull
uv sync
python -m braindump upgrade
# 内部执行：
# 1. cp braindump.db backup/braindump_{timestamp}.db
# 2. 检查 migrations 表，找出未执行的迁移
# 3. 按顺序执行
# 4. 更新 migrations 表
```

### 回滚

```bash
# 最坏情况：直接恢复备份
cp backup/braindump_{timestamp}.db braindump.db

# 或者：从文件系统完全重建
python -m braindump rebuild-index
```

---

## 11. 后续可扩展方向（不在 V1 范围）

- [ ] Memos 数据导入
- [ ] LLM 摘要（视频/语音转写后生成一句话摘要）
- [ ] 语义搜索（本地 embedding 模型）
- [ ] 随机回顾（定时推送旧笔记到 Telegram）
- [ ] 多媒体时间修复（从 EXIF/媒体元数据恢复原始时间）
- [ ] 导出（Markdown / JSON / PDF）
- [ ] 简单认证（Web UI 密码保护）
- [ ] 云端备份（rclone 同步到百度网盘，开发但暂不启用）

---

## 12. V1 交付目标

能跑起来的最小可用版本：

1. ✅ Telegram Bot 接收文字/图片/视频/语音
2. ✅ 文件按规则存储到本地目录
3. ✅ 视频和语音自动转写（FunASR Paraformer-large，可切换）
4. ✅ Web UI 时间线浏览 + 播放 + 转写显示
5. ✅ Flomo 导入脚本
6. ✅ `rebuild-index` 可从文件系统恢复数据库
7. ✅ 软删除（trash/）+ 物理删除（purge + 强确认）

**数据安全优先，功能可以后加，文件不能丢。**
