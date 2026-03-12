# braindump v0.2 设计文档

> 经 Codex (GPT-5.4) + Claude Code (Opus) 双重 review 后的修订版。
> 原始 review: /tmp/claude-review-v02-result.md

## 目标

在 v0.1 基础上实现两个方向的增强：

1. **稳定性** — 让 Docker 部署的 bot 能长期无人值守运行
2. **核心价值** — LLM 摘要 + 每日回顾，让积累的表达真正有用

---

## 一、稳定性增强

### 1.1 日志系统

**现状**：全部用 print，生产环境无法分级过滤。

**改造**：
- 统一使用 `logging.getLogger("braindump")` 替代所有 print
- 日志级别：DEBUG（开发）/ INFO（正常）/ WARNING / ERROR
- 格式：`%(asctime)s %(name)s %(levelname)s: %(message)s`
- 关键字段：`note_id`、`source_id`、`media_type`（结构化便于排查）
- **不要在日志中打印 API Key 或 Bot Token**

### 1.2 Handler 错误处理

**方案**：统一错误装饰器，包裹所有 handler。

```python
def safe_handler(func):
    async def wrapper(client, message):
        try:
            await func(client, message)
        except Exception as e:
            logger.error(f"Handler {func.__name__} failed: {e}", exc_info=True)
            try:
                # 个人工具，直接显示错误详情（比 "请重试" 有用）
                await message.reply_text(f"❌ 保存失败: {e}")
            except Exception:
                pass  # reply 也失败了，只能靠日志
    return wrapper
```

- 错误回复包含具体原因（磁盘满、网络断等）— 只有自己用，不需要隐藏
- reply 本身失败时静默（可能已断线），日志已记录

### 1.3 进程管理

**方案**：用 `asyncio.TaskGroup`（Python 3.11+）替代 `asyncio.gather()`。

```python
async def _serve_all():
    async with asyncio.TaskGroup() as tg:
        tg.create_task(run_web())
        tg.create_task(run_bot())
        tg.create_task(run_transcribe_worker())
        tg.create_task(run_summary_worker())
        tg.create_task(run_review_scheduler())
    # TaskGroup 保证：任一 task 崩溃 → 全部取消 → 主进程退出 → Docker 重启
```

启动时打印版本号 + 配置摘要（data_dir、引擎、LLM 模型、回顾时间等）。

### 1.4 健康检查

**端点**：`GET /health` — 返回各组件状态。

```json
{
  "status": "ok",
  "version": "0.2.0",
  "bot": "connected",
  "transcribe": { "engine": "whisper-small", "queue": 0 },
  "summary": { "queue": 0 },
  "last_review": "2026-03-13T09:00:00+08:00"
}
```

- `/health` 需要**绕过 token 认证中间件**（否则 Docker healthcheck 需要传 token）
- 不用 curl（slim 镜像没有），用 Python：

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1
```

### 1.5 转写 Worker 启动扫描

**问题**：如果容器在转写/摘要过程中重启，`processing` 状态的笔记会永久卡住。

**方案**：Worker 启动时，将所有 `processing` 状态重置为 `pending`：

```sql
UPDATE notes SET transcribe_status = 'pending' WHERE transcribe_status = 'processing';
UPDATE notes SET summarize_status = 'pending' WHERE summarize_status = 'processing';
```

### 1.6 ffmpeg 音轨提取（从 Phase 3 提前到 Phase 1）

**原因**：whisper 处理原始视频文件效果差且慢。摘要依赖转写质量，必须先解决输入质量。

```bash
ffmpeg -i video.mp4 -vn -acodec libopus audio.ogg
```

- 提取到临时目录（`tempfile.mkdtemp`），转写完成后删除
- 崩溃后的孤立临时文件：启动时清理 `data_dir/tmp/` 下超过 1 小时的文件

### 1.7 大视频下载

- **进度反馈**：用 `edit_message` 更新进度（每 20% 更新一次，间隔 ≥3 秒，避免 Telegram 限流）
- **磁盘空间检查**：下载前 `shutil.disk_usage(config.data_dir)`，剩余空间 < 文件大小 × 1.5 时拒绝并提示
- **超时**：Pyrofork `download_media` 无原生超时，用 `asyncio.wait_for(download, timeout=1800)` — 30 分钟足够几百 MB

### 1.8 Docker 改进

```yaml
# docker-compose.yml
services:
  braindump:
    build: .
    container_name: braindump
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./data:/data
    environment:
      - BRAINDUMP_DATA_DIR=/data
      - MOONSHOT_API_KEY=${MOONSHOT_API_KEY}
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
```

---

## 二、LLM 摘要

### 2.1 概述

转写完成后自动调用 LLM API 生成结构化摘要。

### 2.2 API 配置

```toml
[llm]
enabled = true                    # 可关闭（离线部署、省钱）
base_url = "https://api.moonshot.cn/v1"
model = "kimi-k2.5"
api_key_env = "MOONSHOT_API_KEY"  # 从环境变量读取
timeout = 30                      # API 请求超时（秒）
min_content_length = 30           # 少于 30 字不生成摘要
```

- API Key **只从环境变量读取**，不写进 config 文件
- 启动时若 `enabled=true` 但环境变量为空，**日志 WARNING 并自动禁用**（不崩溃）
- 底层用 `openai` Python SDK，`base_url` 可配 — 一套代码兼容所有 OpenAI-compatible API

### 2.3 摘要格式

```json
{
  "title": "关于 Agent 落地的思考",
  "summary": "讨论了当前 Agent 系统在实际业务中落地的三个关键瓶颈...",
  "tags": ["agent", "LLM", "观点"],
  "mood": "思考"
}
```

字段说明：
- **title** — 短标题（**15 字以内**），用于时间线显示
- **summary** — 核心内容概括（50-100 字）
- **tags** — 自动提取的主题标签（补充用户手动打的 #标签）
- **mood** — 表达的情绪/类型（见下方枚举）

**mood 枚举**（扩展版）：
`思考` `灵感` `吐槽` `分享` `感悟` `记录` `日常` `工作` `学习` `情绪`

不限死枚举 — LLM 可以从中选，也可以自由发挥，只要是 2-4 字的短标签。

### 2.4 触发时机 + Pipeline

```
消息接收 → 文件保存 → 入库（summarize_status = 'pending' 或 'skipped'）
                         ↓
              TranscribeWorker（音频/视频）
                         ↓ transcribe_status = 'done'
              SummaryWorker（独立 worker，轮询 pending）
                         ↓ summarize_status = 'done'
              更新 .md frontmatter + 回复用户
```

**SummaryWorker 独立于 TranscribeWorker**（松耦合）：
- 轮询 `summarize_status = 'pending'` 的笔记
- 既处理转写后的音视频笔记，也处理纯文字笔记
- 统一逻辑，不在 bot handler 或 transcribe worker 中调 LLM

**触发规则**：
- 纯文字笔记（≥30 字）：创建时 `summarize_status = 'pending'`
- 音频/视频笔记：转写完成后设为 `pending`
- 短文字（<30 字）、纯图片：`summarize_status = 'skipped'`
- 摘要失败：`summarize_status = 'failed'`（不阻塞其他笔记）

### 2.5 数据库改动

```sql
-- migrations/002_ai_summary.sql
ALTER TABLE notes ADD COLUMN ai_title TEXT;
ALTER TABLE notes ADD COLUMN ai_summary TEXT;
ALTER TABLE notes ADD COLUMN ai_tags TEXT;          -- JSON array string
ALTER TABLE notes ADD COLUMN ai_mood TEXT;
ALTER TABLE notes ADD COLUMN ai_model TEXT;          -- 记录用了哪个模型
ALTER TABLE notes ADD COLUMN ai_generated_at TEXT;   -- 摘要生成时间（方便以后换模型重跑）
ALTER TABLE notes ADD COLUMN summarize_status TEXT DEFAULT 'pending';
  -- pending | processing | done | skipped | failed

-- 回顾记录
CREATE TABLE IF NOT EXISTS review_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id INTEGER NOT NULL,
  sent_at TEXT NOT NULL,
  FOREIGN KEY (note_id) REFERENCES notes(id)
);

-- FTS 更新：加入 AI 字段
DROP TRIGGER IF EXISTS notes_ai;
-- 在应用层处理 FTS 更新，不用触发器
```

**FTS 索引扩展**：将 `ai_title`、`ai_summary` 加入 FTS5，让搜索能命中摘要内容。

### 2.6 JSON 解析健壮性

LLM 经常在 JSON 外面包 markdown code fence。解析流程：

```python
def parse_llm_json(text: str) -> dict:
    # 1. 去掉 ```json ... ``` 包裹
    text = re.sub(r'^```(?:json)?\s*\n?', '', text.strip())
    text = re.sub(r'\n?```\s*$', '', text)
    # 2. 尝试 json.loads
    # 3. 失败则 status='failed'，日志记录原始返回
    return json.loads(text)
```

如果 Kimi 支持 `response_format: {"type": "json_object"}`，优先使用。

### 2.7 Prompt

```
System:
你是一个个人笔记助手。用户通过语音、视频或文字记录了个人想法。
请分析内容并生成结构化摘要，以 JSON 格式返回。

User:
内容类型：{media_type}（{duration}秒）
原文：
{content}

请返回 JSON：
{{
  "title": "简短标题（15字以内）",
  "summary": "核心内容概括（50-100字）",
  "tags": ["标签1", "标签2"],
  "mood": "2-4字情绪标签，如：思考、灵感、吐槽、日常、工作、学习"
}}

注意：
- 保持用户原始的语气和观点，不要美化或改写
- tags 提取内容主题关键词，2-5 个，不要太泛（不要用"笔记"、"想法"这种）
- 原文可能来自语音识别，包含错别字或断句问题，请根据上下文理解原意
- 如果内容太短或没有实质信息，title 用原文前几个字，summary 简短概括即可
- 使用中文回复（除非原文是英文）
```

改进点（vs 初版）：
- System/User prompt 分离 → 更稳定的输出
- title 放宽到 15 字 → 更自然
- mood 不限死枚举 → 灵活
- 明确语音识别错误处理 → 避免总结出乱码
- 标签负面示例 → 避免无用标签
- 语言指令 → 中英文自适应

### 2.8 成本预估

- Kimi K2.5：input 免费，output ¥9/million tokens
- 每条笔记 ~200 tokens output
- 每天 10 条 ≈ ¥0.018/天 ≈ **几乎免费**
- 注意：价格可能调整，建议在 config 中预留每日预算限制字段（v0.2 不实现，v0.3 考虑）

### 2.9 失败重试

**不做自动重试**（LLM API 失败通常是限流或服务端问题，自动重试可能加剧）。

**提供手动重试**：
- CLI 命令：`braindump retry-summary [--all | --note-id 123]`
- 将 `failed` 状态重置为 `pending`，SummaryWorker 自动拾取
- 同样适用于转写：`braindump retry-transcribe [--all | --note-id 123]`

### 2.10 历史笔记回填

~900 条 Flomo 导入的笔记**不自动回填摘要**：
- 节省 API 调用
- Flomo 笔记通常很短，摘要价值低
- 提供 CLI 命令供手动触发：`braindump summarize --backfill [--min-length 50]`

---

## 三、Frontmatter（.md 文件元数据）

### 3.1 目标

让 `.md` 文件自包含 — 不依赖数据库也能获取完整元数据。

### 3.2 格式

```markdown
---
title: 关于 Agent 落地的思考
tags: [agent, LLM, 观点]
mood: 思考
created: 2026-03-12T22:35:13+08:00
source: telegram
type: text
---

原文内容...
```

### 3.3 写入时机

| 阶段 | 写入内容 |
|------|---------|
| 笔记创建时 | created, source, type, 用户手动 tags |
| 摘要完成后 | title, tags(合并), mood, summary |

**实现**：写入时读取现有文件 → 解析 frontmatter → 合并新字段 → 重写文件。

### 3.4 现有文件迁移

- 提供 CLI 命令：`braindump migrate-frontmatter`
- 从数据库读取元数据，写入对应 `.md` 文件
- **幂等**：已有 frontmatter 的文件跳过或合并
- 音频/视频笔记**不创建 .md 文件** — 它们的元数据在数据库中，真实数据是音视频文件本身

### 3.5 rebuild-index 适配

`rebuild-index` 命令需要：
- 解析 `.md` 文件的 YAML frontmatter
- 将 frontmatter 中的 AI 字段恢复到数据库
- 保持向后兼容：没有 frontmatter 的旧 `.md` 文件照常处理

---

## 四、每日回顾

### 4.1 概述

每天定时从历史笔记中随机选 3 条，通过 Telegram Bot 推送给用户。

### 4.2 配置

```toml
[review]
enabled = true
count = 3                       # 每次推送几条
schedule = "09:00"              # 推送时间（用户时区，用 [general] timezone）
min_age_days = 7                # 至少 7 天前的笔记才会被回顾
min_content_length = 20         # 至少 20 字的笔记才有回顾价值
chat_id = 5439573095            # 推送目标（Telegram user ID）
```

- `chat_id` 必须配置 — Bot 主动发消息需要 chat_id
- 默认值：`telegram.allowed_users[0]`（如果只有一个用户）

### 4.3 调度实现

**不用每分钟轮询**。用 `asyncio.sleep(delta)` 精确等待：

```python
async def run_scheduler():
    while True:
        now = datetime.now(tz)
        next_run = compute_next_run(now, schedule_time)
        
        # 如果今天的时间已过但还没发送过，立即发送（处理重启情况）
        if missed_today(now):
            await send_review()
        
        delta = (next_run - now).total_seconds()
        await asyncio.sleep(delta)
        await send_review()
```

### 4.4 推送记录（持久化）

记录在 `review_log` 表中（不是内存）：

```sql
CREATE TABLE review_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  note_id INTEGER NOT NULL,
  sent_at TEXT NOT NULL,
  FOREIGN KEY (note_id) REFERENCES notes(id)
);
```

- 通过 `sent_at` 判断今天是否已发送（避免 Docker 重启后重复推送）
- 通过 `note_id` 记录哪些笔记已推送过（后续可加权重，减少重复）

### 4.5 笔记选取

```sql
SELECT * FROM notes
WHERE created_at < datetime('now', '-{min_age_days} days')
  AND is_deleted = 0
  AND (length(content) > {min_content_length} OR transcript IS NOT NULL)
  AND id NOT IN (
    SELECT note_id FROM review_log 
    WHERE sent_at > datetime('now', '-30 days')  -- 30 天内推过的不重复
  )
ORDER BY RANDOM()
LIMIT {count}
```

**边界情况**：
- 符合条件的笔记不足 3 条 → 有几条发几条，0 条则不发送
- Bot 无法发送（用户拉黑等）→ 日志记录，不重试

### 4.6 推送格式

```
🔄 每日回顾

📅 2026-01-15
关于 Agent 落地的思考
讨论了当前 Agent 系统在实际业务中落地的三个关键瓶颈...

📅 2025-12-03
#读书笔记 《思考快与慢》
系统一和系统二的区别其实就是...

📅 2025-10-20
周末的灵感
突然想到一个关于 prompt caching 的优化方案...
```

- 有 AI 摘要 → 用 `ai_title` + `ai_summary`
- 无摘要 → 用原文前 100 字
- 图片笔记 → 文字加 📷 标记（不发图片，简单为主）

---

## 五、文件变更清单

### 新增文件
```
braindump/llm/
  __init__.py
  summarizer.py            # SummaryWorker + LLM 调用 + JSON 解析
braindump/review/
  __init__.py
  scheduler.py             # ReviewScheduler + 调度 + 推送
migrations/
  002_ai_summary.sql       # AI 字段 + review_log 表
```

### 修改文件
```
braindump/config.py            # [llm] [review] 配置 + 验证
braindump/bot/handlers.py      # safe_handler 装饰器 + 下载进度 + summarize_status 设置
braindump/transcribe/engine.py # 转写完成后设 summarize_status='pending' + 启动扫描
braindump/web/routes.py        # /health 端点（绕过认证）+ 摘要显示
braindump/web/templates/       # 显示 AI 标题/摘要/标签/mood
braindump/web/static/style.css # 摘要样式
braindump/__main__.py          # TaskGroup + retry/backfill/migrate CLI 命令
braindump/database.py          # FTS 更新 + frontmatter 解析
config.example.toml            # [llm] [review] 示例
Dockerfile                     # Python healthcheck
docker-compose.yml             # healthcheck + MOONSHOT_API_KEY
README.md                      # v0.2 功能说明
```

---

## 六、实现顺序

```
Phase 1: 稳定性 + 转写优化（先保证不挂 + 输入质量）
  ├── logging 替代 print
  ├── safe_handler 错误装饰器
  ├── asyncio.TaskGroup 替代 gather
  ├── ffmpeg 音轨提取（视频 → .ogg → whisper）
  ├── 转写 worker 启动扫描（重置 processing → pending）
  ├── /health 端点（绕过认证）
  └── Docker healthcheck（Python, 不用 curl）

Phase 2a: LLM 摘要后端
  ├── 数据库迁移（002_ai_summary.sql）
  ├── SummaryWorker（独立 worker，轮询 pending）
  ├── LLM 客户端（openai SDK + configurable base_url）
  ├── JSON 解析（strip code fence + 错误处理）
  ├── bot handler 设置 summarize_status
  └── retry CLI 命令

Phase 2b: 摘要展示 + Frontmatter
  ├── .md frontmatter 写入/更新
  ├── Web UI 显示 AI 标题/摘要/标签
  ├── FTS 索引扩展
  └── migrate-frontmatter CLI

Phase 3: 大视频优化
  ├── 下载进度反馈（edit_message, ≥3s 间隔）
  ├── 磁盘空间检查
  └── 下载超时（30 分钟）

Phase 4: 每日回顾
  ├── ReviewScheduler（asyncio.sleep 精确调度）
  ├── review_log 持久化
  ├── 笔记选取（排除近期已推送）
  ├── Telegram 推送
  └── serve 集成
```

---

## 七、v0.2 交付标准

- [ ] Docker 部署后可长期无人值守运行（TaskGroup + healthcheck + restart）
- [ ] 全局 structured logging，无 print
- [ ] 视频转写先提取音轨（ffmpeg），质量和速度都提升
- [ ] 几百 MB 视频能下载、有进度反馈、有磁盘检查
- [ ] 音频/视频转写后自动生成结构化 AI 摘要
- [ ] 纯文字笔记（≥30 字）也自动生成摘要
- [ ] .md 文件包含 frontmatter（可独立使用）
- [ ] Web UI 显示 AI 标题/摘要/标签/mood
- [ ] 搜索能命中 AI 摘要内容（FTS 扩展）
- [ ] 每天 09:00 推送 3 条历史回顾到 Telegram
- [ ] 回顾记录持久化，避免重启后重复推送
- [ ] 失败可手动重试（CLI 命令）

---

## 八、不做的事（明确排除）

- ❌ 自动重试（LLM/转写失败不自动重试，手动 CLI 触发）
- ❌ 历史笔记自动回填摘要（提供 CLI 命令，不自动跑）
- ❌ 多用户支持
- ❌ 语义搜索（v0.3）
- ❌ 每日预算限制（v0.3）
- ❌ 音视频笔记的 .md sidecar 文件（元数据在 DB 中就够了）
