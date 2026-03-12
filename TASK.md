# TASK: braindump 前端重写

## 背景
braindump 是个人笔记/表达原材料库，后端 FastAPI + SQLite 已完成，现在要把 Jinja2 模板前端替换为 React SPA。

## 技术栈
- **React 19 + TypeScript + Vite**
- **Tailwind CSS v4**
- **shadcn/ui** — new-york 风格，Claude 主题（oklch warm amber 配色）
  - 安装方式：`npx shadcn@latest init`，选 new-york style
  - 需要的组件按需 `npx shadcn@latest add <component>`
- **React Router v7** — 客户端路由
- **recharts** — 统计图表（shadcn 有 chart 组件封装）
- **marked + KaTeX** — markdown 渲染 + 数学公式
- **暗色模式** — shadcn 原生支持，next-themes 或自实现 class toggle

## 目录结构

```
braindump/
├── frontend/                # React SPA（新建）
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx          # Router 定义
│   │   ├── index.css        # Tailwind + shadcn CSS 变量
│   │   ├── components/
│   │   │   ├── ui/          # shadcn/ui 原子组件
│   │   │   ├── layout/      # Header, Sidebar, ThemeToggle
│   │   │   ├── timeline/    # NoteCard, FilterBar, SearchInput
│   │   │   ├── note/        # NoteDetail, NoteEditor, MediaViewer
│   │   │   ├── dashboard/   # StatsCards, MonthlyChart, TagCloud, TypePie
│   │   │   └── calendar/    # CalendarHeatmap, DayNotesList
│   │   ├── pages/
│   │   │   ├── TimelinePage.tsx
│   │   │   ├── NotePage.tsx
│   │   │   ├── DashboardPage.tsx
│   │   │   └── CalendarPage.tsx
│   │   ├── lib/
│   │   │   ├── api.ts       # fetch wrapper（所有 API 调用）
│   │   │   ├── utils.ts     # cn() + 通用工具
│   │   │   └── markdown.ts  # marked + KaTeX 渲染
│   │   └── hooks/
│   │       ├── use-notes.ts
│   │       └── use-theme.ts
│   ├── public/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts   # 如 v4 需要
│   └── index.html
├── braindump/               # Python 后端（已有，需改造）
│   ├── web/
│   │   ├── app.py           # FastAPI 入口（改造：去模板，serve frontend/dist）
│   │   └── routes.py        # API 路由（改造：去 HTML 路由，加新 API）
│   │   # 删除 templates/ 和 static/ 目录
│   ├── bot/
│   ├── transcribe/
│   ├── database.py
│   └── config.py
├── migrations/
└── tests/
```

## 后端改造

### 1. 清理 routes.py
- 删除 `timeline_page` 和 `note_detail_page`（HTML 路由）
- 删除所有 Jinja2 相关代码
- 所有 API 路由统一加 `/api` 前缀

### 2. 新增 API

**GET /api/notes** — 已有，保持不变

**GET /api/notes/{id}** — 单条笔记详情（含 attachments）
```json
{
  "id": 1,
  "content": "...",
  "media_type": "text",
  "tags": "tag1,tag2",
  "created_at": "2026-03-12T10:30:00",
  "display_date": "2026-03-12",
  "source": "telegram",
  "attachments": [...],
  "transcript": "..."
}
```

**PUT /api/notes/{id}** — 编辑笔记
- Body: `{ "content": "...", "tags": "..." }`
- 返回更新后的 note

**POST /api/notes** — 新建笔记
- Body: `{ "content": "...", "tags": "..." }`
- 自动设 source="web", media_type="text"

**DELETE /api/notes/{id}** — 已有，保持

**POST /api/notes/{id}/restore** — 已有，保持

**GET /api/stats** — 统计数据
```json
{
  "total": 894,
  "by_type": { "text": 700, "image": 150, "audio": 30, "video": 14 },
  "by_source": { "flomo": 800, "telegram": 94 },
  "by_month": [
    { "month": "2026-03", "count": 45 },
    { "month": "2026-02", "count": 78 }
  ],
  "by_tag": [
    { "tag": "reading", "count": 120 },
    { "tag": "idea", "count": 85 }
  ]
}
```

**GET /api/notes/calendar?year=2026&month=3** — 日历数据
```json
{
  "days": {
    "2026-03-01": 5,
    "2026-03-02": 3,
    "2026-03-12": 12
  }
}
```

**GET /api/tags** — 所有标签列表（已有逻辑，独立为 endpoint）

### 3. app.py 改造
- 删除 templates 相关
- 删除旧 static 挂载
- 保留 media 挂载（`/media/*`）
- 添加：serve `frontend/dist/` 作为 SPA（所有非 `/api` 和 `/media` 请求 → `index.html`）
- 删除 TokenAuthMiddleware（本地部署不需要认证）

## 前端页面设计

### Timeline（首页 `/`）
- 顶部：搜索框 + 类型筛选 chips（All/Text/Image/Video/Audio）+ 标签下拉
- 筛选结果 summary（"894 notes" 或 "12 results"）
- 笔记卡片列表，按日期分组（日期 sticky header）
- 卡片内容：时间、类型 badge、来源标签、标签、内容预览、缩略图
- 无限滚动或分页
- 右下角 FAB 按钮：新建笔记
- 点击卡片 → 跳转 Note Detail

### Note Detail（`/note/:id`）
- 返回按钮
- 完整 markdown 渲染（支持代码高亮、公式）
- 媒体展示（图片 lightbox、视频/音频播放器）
- 转写内容（可折叠）
- 标签展示
- 编辑按钮 → 切换编辑模式（纯文本 textarea，标签输入）
- 删除/恢复按钮

### Dashboard（`/dashboard`）
- 统计卡片：总笔记数、本月新增、最活跃日、标签数
- 月度趋势折线图（recharts）
- 类型分布饼图
- 标签 Top 20 柱状图
- 来源分布

### Calendar（`/calendar`）
- 月历视图（类似 GitHub contribution heatmap 或传统月历）
- 每个日期格显示笔记数量（颜色深浅表示密度）
- 点击日期 → 展开当天笔记列表
- 月份切换

### 全局布局
- 顶部 Header：logo "🧠 braindump" + 导航（Timeline / Dashboard / Calendar）+ 暗色模式切换
- 移动端：底部 tab 导航
- 响应式：手机优先

## 设计原则（从 apecode-web 学来的）

1. **所有颜色来自 CSS 变量** — 禁止硬编码色值，全走 shadcn 主题 token
2. **Claude 主题配色** — oklch warm amber，shadcn init 时选择
3. **组件优先** — 能用 shadcn 组件就用，不要自己造
4. **留白克制** — 信息密度适中，不塞满
5. **动效轻量** — 微交互用 CSS transition，不要过度动画
6. **暗色模式** — 所有组件和自定义样式都要支持 dark mode

## 开发步骤（建议顺序）

### Phase 1: 基础搭建
1. `frontend/` 目录初始化 Vite + React + TS
2. 安装配置 Tailwind CSS v4 + shadcn/ui（Claude 主题）
3. 配置 React Router，搭建 Layout + 四个空页面
4. 配置 vite proxy → FastAPI（开发用）

### Phase 2: 后端改造
5. 清理 routes.py（删 HTML 路由，统一 /api 前缀）
6. 新增 API endpoints（notes CRUD、stats、calendar、tags）
7. 改造 app.py（serve SPA、删旧模板）
8. 删除 `braindump/web/templates/` 和 `braindump/web/static/`

### Phase 3: Timeline 页面
9. NoteCard 组件 + FilterBar + 搜索
10. 按日期分组展示
11. 分页或无限滚动

### Phase 4: Note Detail 页面
12. markdown 渲染（含代码高亮 + KaTeX 公式）
13. 媒体展示（图片 lightbox、音视频播放）
14. 编辑模式

### Phase 5: Dashboard + Calendar
15. Stats API 对接 + 图表组件
16. 日历视图 + 点击交互

### Phase 6: 收尾
17. 暗色模式全面测试
18. 移动端响应式适配
19. 新建笔记功能
20. 生产构建配置（`vite build` + FastAPI serve dist）

## 注意事项
- Python 后端用 `uv` 管理，不要用 pip
- 前端用 npm 或 pnpm 都行
- 本地部署，一个 Docker 容器跑前后端，不需要认证
- 不需要国际化，中英混用即可（UI 英文为主）
- Git 小步提交，每个有意义的变更都 commit
