# braindump v2 — Design Specification

## 定位

**Voice & Video First 的个人原材料库。** AI-native, Agent-ready, 开源。

核心价值：**数据永久保留，代码随时可换。**

语音和视频是第一输入方式，文字是次要的。用户通过 Telegram Bot 随手 dump 语音、视频、图片、文字、链接，
系统自动转写和索引。原始媒体文件永久保留，content.md 是转写产物，audio/video 是真相。

## 核心原则

1. **文件即真相** — 每条记录是一个自包含目录，包含所有关联资源
2. **SQLite 只是索引** — 可随时从 items/ 目录重建
3. **数据永不丢失** — items 一旦创建就永久保留，代码可以完全重写
4. **向后兼容** — 数据结构只能扩展不能破坏，未来 v3/v4 前端随便换
5. **AI 友好** — 文件用 YAML/Markdown，AI 可直接读取理解

## 数据结构

### 目录布局

```
~/braindump-data/
  config.toml               # 配置文件
  items/                    # 所有记录（这是唯一重要的目录）
    20260619-143052-a3f8/   # 格式: YYYYMMDD-HHmmss-<4位hex>
      item.yaml             # 元数据
      content.md            # 文字内容（用户输入 or 转写结果）
      audio.opus            # 原始语音（可选）
      images/               # 图片目录（可选）
        001.jpg
        002.png
      video.mp4             # 原始视频（可选）
  braindump.db              # SQLite 索引（可从 items/ 重建）
  bot.session               # Telegram Bot session 文件
```

### item.yaml 规范

```yaml
id: "20260619-143052-a3f8"
created_at: "2026-06-19T14:30:52+08:00"
updated_at: "2026-06-19T14:30:52+08:00"
type: thought                # thought | bookmark | note
source: telegram             # telegram | web | cli | api
tags: []
status: active               # active | archived | deleted

# 可选字段
bookmark_url: null           # bookmark 类型的原始链接
summary: null                # AI 生成的一句话摘要
telegram_message_id: null    # 来源消息 ID（溯源用）

# 媒体标记（方便索引，不重复存内容）
has_audio: false
has_images: false
has_video: false
```

### content.md 规范

- 纯 Markdown 格式
- 语音转写的内容直接作为 Markdown 文本
- 用户发的文字消息直接保存
- 如果用户发了链接 + 评论，格式：

```markdown
> https://twitter.com/xxx/status/123

我觉得这个观点很有意思，因为...
```

### ID 生成规则

`YYYYMMDD-HHmmss-XXXX`
- 时间部分：Asia/Shanghai 时区
- XXXX：4 位十六进制随机数
- 目的：人类可读 + 按时间排序 + 唯一性

## 技术栈

- **语言**: Python 3.12+
- **包管理**: uv
- **后端**: FastAPI
- **数据库**: SQLite (aiosqlite)
- **Bot**: Pyrofork (MTProto, 支持大文件)
- **转写**: faster-whisper (small model, CPU)
- **前端**: React 19 + Vite + TypeScript + Tailwind CSS v4 + shadcn/ui
- **LLM**: Kimi K2.5 (摘要, 可选)

## 架构

```
┌─────────────┐  ┌──────────┐  ┌──────────┐
│ Telegram Bot│  │  Web UI  │  │   CLI    │
└──────┬──────┘  └────┬─────┘  └────┬─────┘
       │              │             │
       └──────────────┼─────────────┘
                      │
              ┌───────▼────────┐
              │ braindump-core │  ← 核心 Python 库
              │                │
              │  ItemStore     │  ← 文件读写 (items/)
              │  IndexDB       │  ← SQLite 索引
              │  Transcriber   │  ← 语音转写
              │  Summarizer    │  ← AI 摘要 (可选)
              └────────────────┘
```

### braindump-core API

```python
class BrainDump:
    async def add(self, content: str, *, 
                  type: str = "thought",
                  source: str = "telegram",
                  audio_path: Path | None = None,
                  image_paths: list[Path] | None = None,
                  video_path: Path | None = None,
                  bookmark_url: str | None = None,
                  tags: list[str] | None = None) -> Item

    async def get(self, item_id: str) -> Item | None
    async def list(self, *, type: str | None = None, 
                   tag: str | None = None,
                   limit: int = 50, offset: int = 0) -> list[Item]
    async def search(self, query: str) -> list[Item]
    async def update(self, item_id: str, **kwargs) -> Item
    async def delete(self, item_id: str) -> None  # soft delete: status → deleted
    async def rebuild_index(self) -> int  # 从 items/ 重建 SQLite
```

## Telegram Bot 行为

### 消息处理

| 用户发送 | 处理方式 |
|---------|---------|
| 纯文字 | 直接保存为 thought |
| 语音消息 | 下载 → 转写 → 保存（content.md = 转写文本，保留原始音频） |
| 图片 | 下载保存，如有 caption 作为 content.md |
| 图片 + 文字 | 下载图片 + 文字作为 content.md |
| 视频 | 下载 → 转写音轨 → 保存 |
| 链接 (URL) | 识别为 bookmark 类型，提取 URL |
| 链接 + 评论 | bookmark 类型，URL + 评论 |
| 转发消息 | 保存内容，标记 source info |

### Bot 命令

- `/start` — 欢迎消息
- `/status` — 统计信息（总条数、今日新增等）
- `/recent` — 最近 5 条记录的摘要
- `/search <keyword>` — 搜索

### 智能检测

- 消息包含 URL → 自动标记为 bookmark 类型
- 纯文字 → thought 类型
- 语音/视频 → 先转写再分类

## Web UI 设计

### 设计风格
- **参考**: Flomo 卡片流 + shadcn/ui 组件
- **色调**: 暖色系，柔和背景，干净
- **字体**: Inter (英文) + 思源黑体/系统字体 (中文)
- **响应式**: 桌面和手机浏览器都可用

### 页面结构

**单页应用，一个主页面：**

1. **顶部栏**: braindump logo + 搜索框 + 筛选按钮
2. **筛选栏**: 全部 | 想法 | 收藏 | 按标签（横向 pill 按钮）
3. **卡片流**: 时间倒序排列
   - 每张卡片显示：时间、内容（Markdown 渲染）、标签
   - 语音类型：内嵌音频播放器
   - 图片：缩略图预览，点击放大
   - 链接：显示 URL 卡片样式
   - 操作：标签编辑、删除（软删除）
4. **无限滚动**: 下拉加载更多

### API 端点

```
GET  /api/items          — 列表（支持 ?type=&tag=&q=&limit=&offset=）
GET  /api/items/:id      — 详情
POST /api/items          — 创建（Web/CLI/Agent 写入）
PATCH /api/items/:id     — 更新（标签、状态等）
DELETE /api/items/:id    — 软删除
GET  /api/stats          — 统计
GET  /api/items/:id/audio — 音频流
GET  /api/items/:id/images/:name — 图片
POST /api/rebuild-index  — 重建索引
```

## 配置文件 (config.toml)

```toml
[general]
data_dir = "~/braindump-data"
timezone = "Asia/Shanghai"

[telegram]
api_id = 33926401
api_hash = "xxx"
bot_token = "xxx"
allowed_users = [5439573095]

[transcribe]
engine = "whisper"
whisper_model = "small"
whisper_device = "cpu"

[web]
host = "0.0.0.0"    # 局域网访问
port = 8080

[llm]
enabled = false      # Phase 1 先不开
base_url = "https://api.moonshot.cn/v1"
model = "kimi-k2.5"
api_key_env = "MOONSHOT_API_KEY"
```

## Phase 1 范围（MVP，今天可用）

必须完成：
- [x] 数据结构 (items/ + item.yaml + content.md)
- [x] braindump-core 库 (add, get, list, delete, rebuild_index)
- [x] Telegram Bot (文字、语音、图片、链接)
- [x] 语音转写 (faster-whisper)
- [x] Web UI (卡片流浏览、搜索、筛选)
- [x] FastAPI server (API + 静态文件服务)
- [x] `braindump serve` 命令 (启动 bot + web + transcriber)

不做：
- Web 端写入（Phase 2）
- CLI 工具（Phase 2）
- AI 摘要/自动标签（Phase 2）
- Flomo 导入（Phase 3）
- Agent API / MCP（Phase 3）

## 启动命令

```bash
# 安装
cd ~/work/braindump
uv sync

# 运行（同时启动 bot + web + transcriber）
uv run braindump serve

# 只启动 web
uv run braindump web

# 重建索引
uv run braindump rebuild-index
```

## 测试要求

- 核心库单元测试（ItemStore, IndexDB）
- Bot 消息处理测试（mock Telegram）
- API 端点测试
- 前端构建通过
