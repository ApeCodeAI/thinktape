# braindump v0.2 设计文档

## 目标

在 v0.1 基础上实现两个方向的增强：

1. **稳定性** — 让 Docker 部署的 bot 能长期无人值守运行
2. **核心价值** — LLM 摘要 + 每日回顾，让积累的表达真正有用

---

## 一、稳定性增强

### 1.1 Bot 重连与错误恢复

**现状**：Pyrofork 底层有 TCP 重连，但应用层异常（handler 报错）会导致静默失败。

**方案**：

```
每个 handler 加 try/except，捕获异常后：
1. 记录错误日志（logging，不是 print）
2. 给用户回复错误提示（"保存失败，请重试"）
3. 不让单条消息的异常影响整个 bot
```

改造点：
- [ ] 全局 logging 替代 print（`logging.getLogger("braindump")`)
- [ ] handler 统一错误装饰器
- [ ] Pyrofork `on_disconnect` 回调记录断线日志

### 1.2 大视频支持（几百 MB）

**现状**：代码支持 MTProto 下载（理论 2GB），但只测过小文件。

**需要验证和处理**：
- [ ] 下载进度反馈（每 10% 回复一次进度，或用 `edit_message` 更新）
- [ ] 磁盘空间检查（下载前检查剩余空间）
- [ ] 下载超时处理（几百 MB 可能需要几分钟）
- [ ] 视频转写优化：提取音轨再转写（ffmpeg -i video.mp4 -vn audio.ogg），避免 whisper 处理整个视频文件

### 1.3 进程管理

**方案**：依赖 Docker `restart: unless-stopped`，不加 supervisord。

改造点：
- [ ] `serve` 命令中，任一子进程（bot/web/worker）崩溃时主进程也退出（让 Docker 重启整个容器）
- [ ] 启动时打印版本号和配置摘要
- [ ] 健康检查端点 `GET /health`（Docker HEALTHCHECK 用）

### 1.4 Docker 改进

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s \
  CMD curl -f http://localhost:8080/health || exit 1
```

```yaml
# docker-compose.yml
services:
  braindump:
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
```

---

## 二、LLM 摘要

### 2.1 概述

转写完成后自动调用 Kimi API 生成结构化摘要。

### 2.2 API 配置

```toml
[llm]
provider = "moonshot"           # moonshot | openai-compatible
api_key_env = "MOONSHOT_API_KEY"  # 从环境变量读取
base_url = "https://api.moonshot.cn/v1"
model = "kimi-k2.5"
```

- API Key 从环境变量 `MOONSHOT_API_KEY` 读取（不写进 config 文件）
- Docker 部署时通过 `environment` 或 `.env` 传入

### 2.3 摘要格式

对每条有转写文字的笔记，生成结构化摘要：

```json
{
  "title": "关于 Agent 落地的思考",
  "summary": "讨论了当前 Agent 系统在实际业务中落地的三个关键瓶颈：上下文管理、工具调用可靠性、以及成本控制。认为 2026 年会是 Agent 真正可用的元年。",
  "tags": ["agent", "LLM", "观点"],
  "mood": "思考"
}
```

字段说明：
- **title** — 一个短标题（10 字以内），用于时间线显示
- **summary** — 核心内容概括（50-100 字）
- **tags** — 自动提取的主题标签（补充用户手动打的 #标签）
- **mood** — 表达的情绪/类型：思考、吐槽、灵感、记录、分享

### 2.4 触发时机

```
消息接收 → 文件保存 → 转写（音频/视频）→ 摘要生成 → 入库
                                              ↓
                                        回复用户确认
```

- 转写完成后自动触发摘要
- 纯文字笔记（>50 字）也生成摘要
- 短文字（≤50 字）和图片不生成摘要（没必要）
- 摘要失败不影响笔记保存（降级为无摘要）

### 2.5 数据库改动

```sql
ALTER TABLE notes ADD COLUMN ai_title TEXT;
ALTER TABLE notes ADD COLUMN ai_summary TEXT;
ALTER TABLE notes ADD COLUMN ai_tags TEXT;      -- JSON array
ALTER TABLE notes ADD COLUMN ai_mood TEXT;
ALTER TABLE notes ADD COLUMN summarize_status TEXT DEFAULT 'pending';
  -- pending | done | skipped | failed
```

### 2.6 成本预估

- Kimi K2.5：input ¥0/million tokens（免费输入），output ¥9/million tokens
- 一条 5 分钟语音 ≈ 1000 字转写 ≈ ~1500 tokens input + ~200 tokens output
- 每天 10 条 ≈ 2000 tokens output ≈ ¥0.018/天 ≈ **几乎免费**

### 2.7 Prompt

```
你是一个个人笔记助手。用户通过语音/视频/文字记录了一段个人表达。
请分析以下内容，生成结构化摘要。

内容类型：{media_type}
原文：
{content}

请以 JSON 格式返回：
{
  "title": "简短标题（10字以内）",
  "summary": "核心内容概括（50-100字）",  
  "tags": ["标签1", "标签2"],
  "mood": "思考|吐槽|灵感|记录|分享|感悟"
}

注意：
- 保持用户原始的语气和观点
- tags 提取内容主题，不要太泛
- 如果内容很短或没有实质内容，title 和 summary 简短即可
```

---

## 三、每日回顾

### 3.1 概述

每天定时从历史笔记中随机选 3 条，通过 Telegram Bot 推送给用户。

### 3.2 配置

```toml
[review]
enabled = true
count = 3                       # 每次推送几条
schedule = "09:00"              # 推送时间（用户时区）
min_age_days = 7                # 至少 7 天前的笔记才会被回顾
min_content_length = 20         # 至少 20 字的笔记才有回顾价值
```

### 3.3 推送格式

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

- 有 `ai_title` + `ai_summary` 就用摘要
- 没有就用原文前 100 字
- 有图片附上缩略图

### 3.4 实现

```python
# braindump/review/scheduler.py
class ReviewScheduler:
    """每日回顾调度器"""
    
    async def pick_notes(self, count: int = 3) -> list[Note]:
        """随机选取历史笔记"""
        # SELECT * FROM notes 
        # WHERE created_at < now() - min_age_days
        # AND (length(content) > min_content_length OR transcript IS NOT NULL)
        # ORDER BY RANDOM() LIMIT count
        
    async def format_message(self, notes: list[Note]) -> str:
        """格式化推送消息"""
        
    async def send_review(self):
        """发送到 Telegram"""
```

调度方式：
- 在 `serve` 命令中启动一个 asyncio 定时任务
- 每分钟检查一次是否到了推送时间
- 记录上次推送时间，避免重复推送

---

## 四、导出 — 不需要单独做

Chaofa 说得对：**文件系统天然就是导出**。

- 文字笔记已经是 `.md` 文件
- 按 `year/month/day` 组织，人类可读
- 想要某天的内容，直接 `ls ~/braindump-data/media/text/2026/03/12/`
- 想要全部文字，`find ~/braindump-data/media/text -name "*.md"`

唯一可能需要的：把 AI 摘要也写入 `.md` 文件的 frontmatter：

```markdown
---
title: 关于 Agent 落地的思考
tags: [agent, LLM, 观点]
mood: 思考
created: 2026-03-12T22:35:13+08:00
source: telegram
---

原文内容...
```

这样 `.md` 文件本身就是完整的、可独立使用的笔记。**v0.2 实现这个。**

---

## 五、文件变更清单

### 新增文件
```
braindump/llm/
  __init__.py
  summarizer.py          # LLM 摘要服务
braindump/review/
  __init__.py
  scheduler.py           # 每日回顾调度
migrations/
  002_ai_summary.sql     # 摘要字段
```

### 修改文件
```
braindump/config.py          # 新增 [llm] [review] 配置
braindump/bot/handlers.py    # 错误处理装饰器 + 下载进度 + 摘要触发
braindump/transcribe/engine.py  # 转写完成后触发摘要
braindump/web/routes.py      # /health 端点 + 摘要显示
braindump/web/templates/     # 显示 AI 标题/摘要/标签
braindump/__main__.py        # serve 加入 review scheduler
config.example.toml          # 新增配置项
Dockerfile                   # 加 HEALTHCHECK + curl
docker-compose.yml           # 加 healthcheck + env
```

---

## 六、实现顺序

```
Phase 1: 稳定性基础（先保证不挂）
  ├── logging 替代 print
  ├── handler 错误装饰器
  ├── /health 端点
  ├── serve 进程管理（子进程挂了就退出）
  └── Docker healthcheck

Phase 2: LLM 摘要
  ├── 数据库迁移（002_ai_summary.sql）
  ├── summarizer.py（Kimi API 调用）
  ├── 转写完成 → 自动摘要
  ├── .md 文件写入 frontmatter
  └── Web UI 显示摘要

Phase 3: 大视频 + 下载优化
  ├── ffmpeg 提取音轨再转写
  ├── 下载进度反馈
  └── 磁盘空间检查

Phase 4: 每日回顾
  ├── scheduler + 定时任务
  ├── Telegram 推送
  └── 回顾记录（避免重复）
```

---

## 七、v0.2 交付标准

- [ ] Docker 部署后可长期无人值守运行
- [ ] 音频/视频转写后自动生成结构化摘要
- [ ] .md 文件包含 frontmatter（AI 标题、标签、摘要）
- [ ] Web UI 显示 AI 摘要和标签
- [ ] 每天 09:00 推送 3 条历史回顾到 Telegram
- [ ] 几百 MB 视频能正常下载和转写
