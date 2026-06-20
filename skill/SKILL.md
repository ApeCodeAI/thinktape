---
name: thinktape
description: >-
  Voice & Video First personal dump tool — record thoughts, voice memos, videos, bookmarks via CLI.
  Use when: (1) user asks to remember/record/dump something,
  (2) a discussion produces insights worth preserving,
  (3) user says "记一下", "dump this", "save this thought",
  (4) you want to proactively save valuable context for the user.
  AI-first CLI: default JSON output, pipe-friendly, stdin support.
  Supports [[wikilinks]] for bi-directional linking between items.
---

# ThinkTape — Voice & Video First Personal Dump

ThinkTape is the user's Voice & Video First personal raw-material library.
Voice and video are the primary input — local Whisper auto-transcribes.
Original media files are preserved forever (content.md is the transcript, audio/video is the truth).
Supports [[wikilinks]] for bi-directional linking between items.

**When to use this skill:**
- User explicitly asks to record/remember something
- A discussion produces insights worth preserving (ask first)
- User says "记一下", "dump", "记录", "save this"
- You need to retrieve what the user has previously dumped

## Quick Reference

```bash
# Add a thought
thinktape add "content here"

# Add with tags
thinktape add --tag "AI" --tag "想法" "content"

# Add a bookmark
thinktape add --type bookmark --bookmark-url "https://..." "my commentary on this link"

# Add from stdin (pipe-friendly)
echo "content" | thinktape add -

# Add from file
thinktape add --file /path/to/notes.md --tag "笔记"

# Add with media
thinktape add --audio /path/to/voice.opus "optional text"
thinktape add --image /path/to/photo.jpg "optional caption"

# List recent items
thinktape list --limit 10

# List today's items (human-readable)
thinktape list --today --human

# Search
thinktape search "关键词"

# Get one item (full JSON)
thinktape get <item-id>

# Get raw content only (for piping to LLM)
thinktape get <item-id> --content

# Stats
thinktape stats

# All tags
thinktape tags

# Update
thinktape update <item-id> --tag "新标签"
thinktape update <item-id> --content "updated content"

# Delete (soft delete by default)
thinktape delete <item-id>

# AI summarize
thinktape summarize <item-id>
thinktape summarize --all
```

## Output Format

**Default: JSON to stdout** (machine-parseable for agents)

```bash
$ thinktape add "想法"
{"id":"20260619-215030-a3f8","created_at":"2026-06-19T21:50:30+08:00","type":"thought","source":"cli","tags":[],"status":"active"}

$ thinktape list --limit 2
{"items":[...],"total":42}

$ thinktape stats
{"total":42,"today":5,"by_type":{"thought":30,"bookmark":10},"by_tag":{"AI":15}}
```

**`--human` flag for human-readable output** (use when showing to user)

```bash
$ thinktape list --human --limit 3
  20260619-2150  💭  今天的想法...  #AI
  20260619-1909  🔖  Karpathy 教程  #学习
```

**`--content` flag for raw text** (pipe to LLM)

```bash
$ thinktape get 20260619-2150 --content
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
~/thinktape-data/items/20260619-215030-a3f8/
  item.yaml      # Metadata (type, tags, timestamps)
  content.md     # The actual content (Markdown)
  audio.opus     # Voice recording (optional)
  images/        # Photos (optional)
```

**Data is permanent. Code is temporary.** Items survive any code rewrite.

## Common Agent Patterns

### Record a discussion insight
```bash
thinktape add --tag "讨论" --tag "thinktape" \
  "ThinkTape 的核心定位：AI 时代的个人原材料库，voice-first, AI-native, agent-ready"
```

### Save a link the user shared
```bash
thinktape add --type bookmark \
  --bookmark-url "https://example.com/article" \
  --tag "阅读" \
  "用户觉得这篇文章关于 Agent 记忆的观点很有价值"
```

### Retrieve context about a topic
```bash
thinktape search "Agent 架构" | jq -r '.items[].content'
```

### Get today's dumps for daily review
```bash
thinktape list --today
```

### Pipe content to LLM for analysis
```bash
thinktape search "产品想法" | jq -r '.items[].content' | llm "总结共同主题"
```

## Important Notes

- Always use `thinktape add` (not direct file writes) — it maintains the SQLite index
- Default type is `thought` — only specify `--type` when it's clearly a bookmark or note
- Tags are optional but helpful for retrieval — add 1-3 relevant tags
- Content should be in the user's own words / the user's perspective
- Don't dump trivial or temporary things (test messages, casual greetings)
- Ask before dumping discussion content — the user should know what's being saved
- Errors output JSON to stderr with exit code 1

## Prerequisites

- ThinkTape installed: `cd ~/work/thinktape && uv sync`
- Data directory: `~/thinktape-data/`
- Config: `~/thinktape-data/config.toml`
- Run with: `cd ~/work/thinktape && uv run thinktape <command>`
