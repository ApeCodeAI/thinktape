---
name: braindump
description: >-
  Personal dump tool — record thoughts, bookmarks, voice memos via CLI.
  Use when: (1) user asks to remember/record/dump something,
  (2) a discussion produces insights worth preserving,
  (3) user says "记一下", "dump this", "save this thought",
  (4) you want to proactively save valuable context for the user.
  AI-first CLI: default JSON output, pipe-friendly, stdin support.
---

# braindump — Personal Dump CLI

braindump is the user's personal raw-material library. Use it to record thoughts,
bookmarks, voice memos, and any content the user wants to preserve.

**When to use this skill:**
- User explicitly asks to record/remember something
- A discussion produces insights worth preserving (ask first)
- User says "记一下", "dump", "记录", "save this"
- You need to retrieve what the user has previously dumped

## Quick Reference

```bash
# Add a thought
braindump add "content here"

# Add with tags
braindump add --tag "AI" --tag "想法" "content"

# Add a bookmark
braindump add --type bookmark --bookmark-url "https://..." "my commentary on this link"

# Add from stdin (pipe-friendly)
echo "content" | braindump add -

# Add from file
braindump add --file /path/to/notes.md --tag "笔记"

# Add with media
braindump add --audio /path/to/voice.opus "optional text"
braindump add --image /path/to/photo.jpg "optional caption"

# List recent items
braindump list --limit 10

# List today's items (human-readable)
braindump list --today --human

# Search
braindump search "关键词"

# Get one item (full JSON)
braindump get <item-id>

# Get raw content only (for piping to LLM)
braindump get <item-id> --content

# Stats
braindump stats

# All tags
braindump tags

# Update
braindump update <item-id> --tag "新标签"
braindump update <item-id> --content "updated content"

# Delete (soft delete by default)
braindump delete <item-id>

# AI summarize
braindump summarize <item-id>
braindump summarize --all
```

## Output Format

**Default: JSON to stdout** (machine-parseable for agents)

```bash
$ braindump add "想法"
{"id":"20260619-215030-a3f8","created_at":"2026-06-19T21:50:30+08:00","type":"thought","source":"cli","tags":[],"status":"active"}

$ braindump list --limit 2
{"items":[...],"total":42}

$ braindump stats
{"total":42,"today":5,"by_type":{"thought":30,"bookmark":10},"by_tag":{"AI":15}}
```

**`--human` flag for human-readable output** (use when showing to user)

```bash
$ braindump list --human --limit 3
  20260619-2150  💭  今天的想法...  #AI
  20260619-1909  🔖  Karpathy 教程  #学习
```

**`--content` flag for raw text** (pipe to LLM)

```bash
$ braindump get 20260619-2150 --content
今天的想法...
```

## Item Types

| Type | Use for | Icon |
|------|---------|------|
| `thought` (default) | Ideas, feelings, observations | 💭 |
| `bookmark` | Links with commentary | 🔖 |
| `note` | Structured notes, meeting notes | 📝 |

## Data Structure

Each item is a self-contained directory:
```
~/braindump-data/items/20260619-215030-a3f8/
  item.yaml      # Metadata (type, tags, timestamps)
  content.md     # The actual content (Markdown)
  audio.opus     # Voice recording (optional)
  images/        # Photos (optional)
```

**Data is permanent. Code is temporary.** Items survive any code rewrite.

## Common Agent Patterns

### Record a discussion insight
```bash
braindump add --tag "讨论" --tag "braindump" \
  "braindump 的核心定位：AI 时代的个人原材料库，voice-first, AI-native, agent-ready"
```

### Save a link the user shared
```bash
braindump add --type bookmark \
  --bookmark-url "https://example.com/article" \
  --tag "阅读" \
  "用户觉得这篇文章关于 Agent 记忆的观点很有价值"
```

### Retrieve context about a topic
```bash
braindump search "Agent 架构" | jq -r '.items[].content'
```

### Get today's dumps for daily review
```bash
braindump list --today
```

### Pipe content to LLM for analysis
```bash
braindump search "产品想法" | jq -r '.items[].content' | llm "总结共同主题"
```

## Important Notes

- Always use `braindump add` (not direct file writes) — it maintains the SQLite index
- Default type is `thought` — only specify `--type` when it's clearly a bookmark or note
- Tags are optional but helpful for retrieval — add 1-3 relevant tags
- Content should be in the user's own words / the user's perspective
- Don't dump trivial or temporary things (test messages, casual greetings)
- Ask before dumping discussion content — the user should know what's being saved
- Errors output JSON to stderr with exit code 1

## Prerequisites

- braindump installed: `cd ~/work/braindump && uv sync`
- Data directory: `~/braindump-data/`
- Config: `~/braindump-data/config.toml`
- Run with: `cd ~/work/braindump && uv run braindump <command>`
