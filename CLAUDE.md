# braindump — Claude 协作指引

> 个人表达原材料库。文件即真相 + SQLite 索引；Telegram + CLI 入，Web / AI 取。
>
> **定位 / 当前阶段 / 路线 / 已决议事项**全部在 second-brain：
> `~/work/second-brain/projects/braindump/`（`index.md` / `_ai-context.md` / `discussions/`）
> 跨工具决策流水：`~/work/second-brain/_ai/memory/daily/<YYYY-MM-DD>.md`

## 不变量

1. **文件即真相，DB 是索引**：原始文件按 `~/braindump-data/media/<type>/YYYY/MM/DD/` 存；SQLite 任何时候都能从文件 + `.md` frontmatter 重建（`rebuild-index`）。
2. **三个目录 / 字段不能动**：`media/` 原始文件、`transcripts/` 转写文本、`.md` 已落 frontmatter 字段名（`created / source / type / tags / title / summary / mood`）。改字段名 = 破坏向后兼容。
3. **Secrets 不入 `config.toml`**：API Key、Bot Token 只通过环境变量；config 里存的是变量名。
4. **Schema 改动 = migration**：在 `migrations/` 加新文件，并验证 `rebuild-index` 仍能从文件恢复出新 schema。
5. **前端改后必须 `cd frontend && npm run build`**，否则 `frontend/dist/` 缺失 → 404。
6. **CLI 命令必须有 `--json`**，退出码语义化（`0` = ok，非 `0` = 失败）。
7. **CLI 输出格式用 `emit()` 统一**（`braindump/cli.py`）：默认人类可读，`--json` 走机器路径。

## 跑、测、构建

```bash
# 后端 dev
uv sync
uv run python -m braindump web      # 仅 Web (http://localhost:8080)
uv run python -m braindump serve    # 全部（Bot + Web + 转写 + 摘要 + Review）

# CLI 试一下
uv run python -m braindump init --json
uv run python -m braindump add "测试一下 CLI #test" --json
uv run python -m braindump list --limit 5 --json

# 前端 dev
cd frontend && npm install && npm run dev   # http://localhost:5173（代理 API → :8080）

# 测试（绕开真实 Telegram + 前端 E2E）
uv run python -m pytest tests/ -q \
  --ignore=tests/test_web_e2e.py \
  --ignore=tests/test_frontend_e2e.py \
  --ignore=tests/test_telegram_bot.py

# 前端构建（部署 / 完整 E2E 前必跑）
cd frontend && npm run build
```

> `tests/test_telegram_bot.py::test_get_updates` 真实访问 Telegram API，本机经 `127.0.0.1:7890` 代理 SSL 握手超时是已知现象，本地验证排除即可。

## AI 操作流程

- **复杂任务**：用 `braindump-dev` Skill（worktree → TASK.md → Claude Code PTY → 测试 → review → 合并）。
- **简单改动**：直接 edit + 跑相关 pytest 即可。
- **"盯着"任务**：定期读 PTY 日志并主动汇报，不要空泛说"在跑"。
- **新增 CLI 命令**：默认人类输出 + 加 `--json` 走 AI 路径，复用 `emit()`；命令必须能被 `rebuild-index` 反向恢复。
- **AI 调用 braindump**：优先 `braindump <cmd> --json`，**不要**直连 SQLite 或绕过 CLI 写 `media/`。

## 仓库结构

- `braindump/` — 后端 Python 包
- `frontend/` — React 19 + Vite + Tailwind v4 + shadcn/ui
- `migrations/` — SQLite schema 迁移
- `tests/` — pytest
- `DESIGN.md` / `DESIGN-v0.2.md` / `DESIGN-v0.3.md` — 历史 / 当前设计文档
- `config.example.toml` — 配置模板
- 数据目录（不入仓库）：`~/braindump-data/`
