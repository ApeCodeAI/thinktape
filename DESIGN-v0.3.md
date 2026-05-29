# braindump v0.3 初始化方向

> 2026-05-29 reboot note. 目标从“能收集并回看”推进到“CLI-first、AI-friendly 的个人表达原材料库”。

## 现状判断

当前代码已经完成 v0.2 的基础产品形态：

- 输入侧：Telegram Bot 支持文字、图片、视频、语音、文件，音视频可转写。
- 存储侧：文件系统是真相，SQLite 是索引；文字笔记写入 Markdown + YAML frontmatter。
- 消化侧：已有 LLM 摘要字段、摘要 worker、每日回顾 scheduler。
- 浏览侧：React SPA 已有 Timeline / Note Detail / Dashboard / Calendar。
- 运维侧：Docker、health check、rebuild-index、retry-summary、migrate-frontmatter 都已具备。

关键缺口也很明确：

- CLI 之前主要是运维入口，不是“记录 / 查询 / 让 AI 调用”的产品入口。
- Web 和 CLI 都会创建文件，但 `rebuild-index` 只识别旧的 `tg/fl/mm/im` 文件名前缀，重建时会漏掉 `web` 文件。
- `braindump.__version__` 仍停在 `0.1.1`，与 README / pyproject 的 `0.2.0` 不一致。
- second-brain 里项目状态仍是暂停后的快照，需要补一份新的重启决策记录。

## v0.3 产品目标

braindump 不做通用笔记，也不先做复杂知识库。它的核心路径是：

1. **低摩擦记录**：人可以用 Telegram / CLI 快速记录，AI 也可以用 CLI 写入。
2. **结构化留痕**：每条内容都有稳定 ID、创建时间、来源、标签、文件路径、frontmatter。
3. **可被 AI 调用**：命令要支持 `--json`，输出可解析，错误码要有语义。
4. **帮助表达**：先把原始材料收集、搜索、回看做好，再做主题聚类、观点挖掘、文章草稿生成。

## CLI-first 基线

第一步初始化以下命令：

```bash
braindump init --json
braindump add "今天想讲的一个观点 #表达" --json
braindump add --stdin --tag article --json
braindump list --limit 20 --json
braindump search "agent 落地" --json
braindump show 123 --json
braindump stats --json
```

这些命令是 AI 调用 braindump 的稳定表面。MCP 暂时不是必要项；CLI + JSON + 清晰退出码更轻。

## 下一阶段

### P0：记录闭环

- `init` 写安全默认配置：Telegram、LLM、Review 默认关闭，避免未配置就报错。
- `add/list/search/show/stats` 支持 `--json`。
- CLI 创建的文件使用 `cli` source，并能被 `rebuild-index` 恢复。

### P1：表达挖掘

- `braindump digest`：按时间范围 / 标签 / 搜索结果汇总素材。
- `braindump cluster`：按主题聚类，输出主题、代表笔记、可展开观点。
- `braindump draft`：基于一组 note id 生成文章 / 视频脚本草稿。
- `braindump review --json`：把每日回顾从 Telegram scheduler 抽成可主动调用的 CLI。

### P2：Web 设计

Web 不先做营销页，也不先重做视觉。等 P1 命令语义稳定后，再用 opendesign 讨论一个“表达工作台”：

- 左侧是时间线 / 搜索 / 标签。
- 中间是当前素材列表。
- 右侧是 AI 挖掘结果：主题、观点、可写方向、草稿入口。
- 移动端优先保证快速回看和编辑，不承载复杂写作工作流。

## 设计原则

- 数据目录仍然是可备份、可迁移、可人工阅读的主资产。
- SQLite 只做索引和查询加速。
- 所有 AI 生成内容必须保留模型、生成时间和可重跑状态。
- CLI 输出默认给人看，`--json` 给 AI / 脚本看。
- Web 只是更好的工作台，不是 braindump 的唯一入口。
