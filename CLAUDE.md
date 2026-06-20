# CLAUDE.md — ThinkTape v2

## 项目概述

ThinkTape 是一个 **Voice & Video First** 的个人思维录音带。AI-native, Agent-ready, 开源。

语音和视频是第一输入方式，文字是次要的。用户通过 Telegram Bot、Web UI 或 CLI 随手 dump 语音、视频、图片、文字、链接，AI 自动转写和摘要，任何 Agent 都可以通过 CLI 直接调用。

**核心原则：数据永久保留，代码随时可换。原始媒体文件是真相，content.md 是转写产物。**

## 必读

- `DESIGN.md` — 完整设计规范，包含数据结构、API、架构、UI 设计

## 技术栈

- Python 3.12+, uv 包管理
- FastAPI + aiosqlite
- Pyrofork (Telegram MTProto)
- faster-whisper (语音转写)
- React 19 + Vite + TypeScript + Tailwind CSS v4 + shadcn/ui

## 项目结构

```
thinktape/
  __init__.py
  core.py          # ThinkTape 类 — 核心业务逻辑
  store.py         # ItemStore — 文件读写 (items/)
  index.py         # IndexDB — SQLite 索引
  bot.py           # Telegram Bot
  transcribe.py    # 语音转写
  web.py           # FastAPI server + API routes
  config.py        # 配置加载
  cli.py           # CLI 入口 (serve/web/rebuild-index)
  models.py        # Pydantic models
frontend/
  src/
    App.tsx
    components/
    ...
  package.json
  vite.config.ts
tests/
  test_store.py
  test_index.py
  test_api.py
pyproject.toml
config.example.toml
DESIGN.md
```

## 开发规则

1. **先读 DESIGN.md**，严格按照数据结构和 API 规范实现
2. **uv 管理依赖**：`uv add <package>`, `uv run pytest`
3. **前端在 frontend/ 目录**：`cd frontend && npm install && npm run build`
4. **构建后的前端放在 frontend/dist/**，FastAPI 通过 StaticFiles 服务
5. **测试**：`uv run pytest tests/ -v`
6. **不要修改 DESIGN.md**
7. **Git**: user.name=apecode, user.email=me@apecode.ai

## 配置

运行时配置在 `~/thinktape-data/config.toml`（不在仓库内）。
仓库内放 `config.example.toml` 作为参考。

## 运行

```bash
uv run thinktape serve    # 启动全部 (bot + web + transcriber)
uv run thinktape web      # 只启动 web
uv run thinktape rebuild-index  # 从 items/ 重建 SQLite 索引
```

## Web UI 设计要求

- Flomo 风格的卡片流，暖色调，干净简洁
- shadcn/ui 组件库
- Markdown 渲染（支持代码块、链接、列表等）
- 内嵌音频播放器
- 图片缩略图 + 点击放大
- 搜索 + 类型筛选 + 标签筛选
- 无限滚动加载
- 响应式设计（桌面 + 手机）
- 中文界面

## 注意事项

- Pyrofork 不是 Pyrogram，import 是 `from pyrogram import ...` 但包名是 `pyrofork`
- faster-whisper 在 macOS x86_64 需要 `onnxruntime<1.24`
- config.toml 不在仓库内，通过 THINKTAPE_DATA_DIR 环境变量或默认 ~/thinktape-data/ 找到
- 前端必须 `npm run build` 生成 dist/，FastAPI 服务 dist/ 静态文件
