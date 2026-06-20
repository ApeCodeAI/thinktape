"""thinktape CLI — AI-first command-line interface.

Default output is JSON to stdout, errors as JSON to stderr.
Use --human for human-readable output.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import click
import uvicorn

from .config import Config, load_config
from .core import ThinkTape
from .models import Item

_VERSION = "2.0.0"
_TZ_CST = timezone(timedelta(hours=8))

_TYPE_ICON = {
    "thought": "💭",
    "bookmark": "🔖",
    "note": "📝",
}
_TYPE_LABEL = {
    "thought": "想法",
    "bookmark": "收藏",
    "note": "笔记",
}


# ============================== helpers ==============================


def _setup_logging(level: str = "WARNING") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def _item_to_dict(item: Item) -> dict[str, Any]:
    d = item.model_dump(mode="json")
    d["images"] = item.images
    return d


def _print_json(data: Any) -> None:
    click.echo(json.dumps(data, ensure_ascii=False, indent=2, default=str))


def _print_err(message: str, code: str = "ERROR") -> None:
    click.echo(
        json.dumps({"error": message, "code": code}, ensure_ascii=False),
        err=True,
    )


def _human_item_line(item: Item) -> str:
    when = item.created_at.astimezone(_TZ_CST).strftime("%Y%m%d-%H%M")
    icon = _TYPE_ICON.get(item.type, "📝")
    if item.has_audio:
        icon = "🎤"
    elif item.has_video:
        icon = "🎬"
    elif item.has_images:
        icon = "🖼️ "
    body = (item.content or "").strip().replace("\n", " ")
    if len(body) > 80:
        body = body[:77] + "…"
    tags = " ".join(f"#{t}" for t in item.tags)
    parts = [f"  {when}", icon, body]
    if item.bookmark_url and not item.bookmark_url in body:
        parts.append(item.bookmark_url)
    if tags:
        parts.append(tags)
    return "  ".join(parts)


def _human_item_detail(item: Item) -> str:
    icon = _TYPE_ICON.get(item.type, "📝")
    label = _TYPE_LABEL.get(item.type, item.type)
    when = item.created_at.astimezone(_TZ_CST).strftime("%Y-%m-%d %H:%M")
    tags = " ".join(f"#{t}" for t in item.tags)
    head = f"{icon} {label}  {when}"
    if tags:
        head += f"  {tags}"
    lines = [head, "─" * 27]
    if item.summary:
        lines.append(f"摘要: {item.summary}")
        lines.append("")
    if item.bookmark_url:
        lines.append(f"链接: {item.bookmark_url}")
        lines.append("")
    if item.content:
        lines.append(item.content.rstrip())
    if item.has_audio:
        lines.append("\n🎤 audio")
    if item.has_video:
        lines.append("\n🎬 video")
    if item.images:
        lines.append("\n🖼️  images: " + ", ".join(item.images))
    return "\n".join(lines)


async def _with_brain(config: Config, fn) -> Any:
    brain = ThinkTape(config)
    await brain.connect()
    try:
        return await fn(brain)
    finally:
        await brain.close()


def _run(coro_fn, ctx: click.Context):
    config = ctx.obj["config"]

    async def runner():
        return await _with_brain(config, coro_fn)

    return asyncio.run(runner())


def _read_stdin_or_file(content: str | None, file: str | None, stdin_marker: bool) -> str:
    """Resolve the content from positional arg / --file / stdin."""
    if file:
        return Path(file).expanduser().read_text(encoding="utf-8")
    if stdin_marker or content == "-":
        return sys.stdin.read()
    return content or ""


def _split_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [t.strip().lstrip("#") for t in value.split(",") if t.strip()]


def _sanitize_config(config: Config) -> dict[str, Any]:
    def _mask(value: str | None) -> str | None:
        if not value:
            return value
        if len(value) <= 6:
            return "***"
        return value[:3] + "…" + value[-3:]

    out: dict[str, Any] = {
        "data_dir": str(config.data_dir),
        "items_dir": str(config.items_dir),
        "db_path": str(config.db_path),
        "timezone": config.timezone,
        "web": {"host": config.web.host, "port": config.web.port},
        "transcribe": {
            "engine": config.transcribe.engine,
            "whisper_model": config.transcribe.whisper_model,
            "whisper_device": config.transcribe.whisper_device,
        },
        "llm": {
            "enabled": config.llm.enabled,
            "base_url": config.llm.base_url,
            "model": config.llm.model,
            "api_key_env": config.llm.api_key_env,
            "api_key_present": bool(os.environ.get(config.llm.api_key_env)),
            "timeout": config.llm.timeout,
            "min_content_length": config.llm.min_content_length,
        },
    }
    if config.telegram is not None:
        out["telegram"] = {
            "api_id": config.telegram.api_id,
            "api_hash": _mask(config.telegram.api_hash),
            "bot_token": _mask(config.telegram.bot_token),
            "allowed_users": config.telegram.allowed_users,
        }
    else:
        out["telegram"] = None
    return out


# ============================== root ==============================


@click.group()
@click.option("--log-level", default="WARNING", show_default=True,
              type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False))
@click.pass_context
def cli(ctx: click.Context, log_level: str):
    """thinktape — AI-first personal dump tool.

    Default output is JSON to stdout. Use --human for human-readable output.
    Errors go to stderr as JSON: {"error": "msg", "code": "..."}.
    """
    _setup_logging(log_level.upper())
    ctx.ensure_object(dict)
    try:
        ctx.obj["config"] = load_config()
    except Exception as e:
        _print_err(f"failed to load config: {e}", code="CONFIG_ERROR")
        sys.exit(1)


# ============================== write ==============================


@cli.command()
@click.argument("content", required=False)
@click.option("--type", "type_", default="thought",
              type=click.Choice(["thought", "bookmark", "note"], case_sensitive=False),
              help="Item type.")
@click.option("--tag", "tags", multiple=True, help="Tag (repeatable).")
@click.option("--tags", "tags_csv", default=None, help="Comma-separated tags.")
@click.option("--audio", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Audio file path (copied into item dir).")
@click.option("--image", "images", multiple=True,
              type=click.Path(exists=True, dir_okay=False),
              help="Image file path (repeatable).")
@click.option("--video", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Video file path.")
@click.option("--file", "file_", type=click.Path(exists=True, dir_okay=False), default=None,
              help="Read content from a file.")
@click.option("--bookmark-url", default=None, help="URL for bookmark type.")
@click.option("--source", default="cli",
              type=click.Choice(["telegram", "web", "cli", "api"], case_sensitive=False),
              help="Source label for the item.")
@click.option("--human", is_flag=True, help="Human-readable output.")
@click.pass_context
def add(
    ctx: click.Context,
    content: str | None,
    type_: str,
    tags: tuple[str, ...],
    tags_csv: str | None,
    audio: str | None,
    images: tuple[str, ...],
    video: str | None,
    file_: str | None,
    bookmark_url: str | None,
    source: str,
    human: bool,
):
    """Add a new item. Pass content positionally, or use - for stdin, or --file PATH."""
    stdin_marker = content == "-"
    body = _read_stdin_or_file(content if not stdin_marker else None, file_, stdin_marker)
    body = (body or "").rstrip("\n")

    if not body and not audio and not images and not video and not bookmark_url:
        _print_err("content is empty — provide content, --file, --audio, --image, --video, or --bookmark-url",
                   code="EMPTY_CONTENT")
        sys.exit(1)

    tag_list = list(tags) + _split_tags(tags_csv)

    async def run(brain: ThinkTape) -> Item:
        return await brain.add(
            content=body,
            type=type_,
            source=source,
            audio_path=Path(audio) if audio else None,
            image_paths=[Path(p) for p in images] if images else None,
            video_path=Path(video) if video else None,
            bookmark_url=bookmark_url,
            tags=tag_list or None,
        )

    item = _run(run, ctx)
    if human:
        click.echo(_human_item_detail(item))
    else:
        _print_json(_item_to_dict(item))


# ============================== read ==============================


@cli.command(name="list")
@click.option("--limit", default=50, show_default=True, type=int)
@click.option("--offset", default=0, show_default=True, type=int)
@click.option("--type", "type_", default=None,
              type=click.Choice(["thought", "bookmark", "note"], case_sensitive=False))
@click.option("--tag", default=None)
@click.option("--status", default="active",
              type=click.Choice(["active", "archived", "deleted", "all"], case_sensitive=False))
@click.option("--since", default=None, help="Only items created on/after ISO date (YYYY-MM-DD).")
@click.option("--today", is_flag=True, help="Shortcut for --since today.")
@click.option("--human", is_flag=True)
@click.pass_context
def list_cmd(
    ctx: click.Context,
    limit: int,
    offset: int,
    type_: str | None,
    tag: str | None,
    status: str,
    since: str | None,
    today: bool,
    human: bool,
):
    """List items. JSON: {items: [...], total: N}."""
    if today:
        now = datetime.now(_TZ_CST)
        since = now.strftime("%Y-%m-%d")

    since_dt: datetime | None = None
    if since:
        try:
            # accept "YYYY-MM-DD" or full ISO
            if "T" in since:
                since_dt = datetime.fromisoformat(since)
            else:
                since_dt = datetime.fromisoformat(since + "T00:00:00").replace(tzinfo=_TZ_CST)
        except ValueError:
            _print_err(f"invalid --since value: {since}", code="BAD_DATE")
            sys.exit(1)

    status_arg: str | None = None if status.lower() == "all" else status

    async def run(brain: ThinkTape) -> list[Item]:
        # Over-fetch a bit when filtering by since.
        fetch_limit = limit if since_dt is None else max(limit * 4, 200)
        items = await brain.list(type=type_, tag=tag, status=status_arg,
                                 limit=fetch_limit, offset=offset)
        if since_dt is not None:
            items = [i for i in items if i.created_at >= since_dt]
        return items[:limit]

    items = _run(run, ctx)
    if human:
        if not items:
            click.echo("(no items)")
            return
        for it in items:
            click.echo(_human_item_line(it))
    else:
        _print_json({
            "items": [_item_to_dict(i) for i in items],
            "total": len(items),
        })


@cli.command()
@click.argument("item_id")
@click.option("--content", "raw_content", is_flag=True,
              help="Output only the raw content.md (no JSON wrapper).")
@click.option("--human", is_flag=True)
@click.pass_context
def get(ctx: click.Context, item_id: str, raw_content: bool, human: bool):
    """Get an item by id."""
    async def run(brain: ThinkTape) -> Item | None:
        return await brain.get(item_id)

    item = _run(run, ctx)
    if item is None:
        _print_err(f"item not found: {item_id}", code="NOT_FOUND")
        sys.exit(1)
    if raw_content:
        click.echo(item.content, nl=False)
        if item.content and not item.content.endswith("\n"):
            click.echo()
        return
    if human:
        click.echo(_human_item_detail(item))
    else:
        _print_json(_item_to_dict(item))


@cli.command()
@click.argument("query")
@click.option("--type", "type_", default=None,
              type=click.Choice(["thought", "bookmark", "note"], case_sensitive=False))
@click.option("--limit", default=50, show_default=True, type=int)
@click.option("--offset", default=0, show_default=True, type=int)
@click.option("--human", is_flag=True)
@click.pass_context
def search(ctx: click.Context, query: str, type_: str | None, limit: int, offset: int, human: bool):
    """Search items by full-text query."""
    async def run(brain: ThinkTape) -> list[Item]:
        items = await brain.search(query, limit=limit, offset=offset)
        if type_:
            items = [i for i in items if i.type == type_]
        return items

    items = _run(run, ctx)
    if human:
        if not items:
            click.echo("(no matches)")
            return
        for it in items:
            click.echo(_human_item_line(it))
    else:
        _print_json({"items": [_item_to_dict(i) for i in items], "total": len(items)})


@cli.command()
@click.option("--human", is_flag=True)
@click.pass_context
def stats(ctx: click.Context, human: bool):
    """Show statistics."""
    async def run(brain: ThinkTape):
        return await brain.stats()

    s = _run(run, ctx)
    if human:
        click.echo(f"总数: {s.total}")
        click.echo(f"今日: {s.today}")
        if s.by_type:
            click.echo("类型: " + ", ".join(f"{k} {v}" for k, v in s.by_type.items()))
        if s.by_tag:
            top = sorted(s.by_tag.items(), key=lambda x: -x[1])[:10]
            click.echo("标签: " + ", ".join(f"#{k} {v}" for k, v in top))
    else:
        _print_json(s.model_dump())


@cli.command()
@click.option("--human", is_flag=True)
@click.pass_context
def tags(ctx: click.Context, human: bool):
    """List all tags."""
    async def run(brain: ThinkTape):
        return await brain.all_tags()

    tag_list = _run(run, ctx)
    if human:
        for t in tag_list:
            click.echo(f"#{t}")
    else:
        _print_json({"tags": tag_list})


# ============================== modify ==============================


@cli.command()
@click.argument("item_id")
@click.option("--content", "new_content", default=None, help="New content text.")
@click.option("--tag", "new_tags", multiple=True, help="Replace tags (repeatable).")
@click.option("--tags", "tags_csv", default=None, help="Comma-separated tags (replaces tags).")
@click.option("--type", "new_type", default=None,
              type=click.Choice(["thought", "bookmark", "note"], case_sensitive=False))
@click.option("--status", "new_status", default=None,
              type=click.Choice(["active", "archived", "deleted"], case_sensitive=False))
@click.option("--summary", "new_summary", default=None)
@click.option("--bookmark-url", "new_url", default=None)
@click.option("--human", is_flag=True)
@click.pass_context
def update(
    ctx: click.Context,
    item_id: str,
    new_content: str | None,
    new_tags: tuple[str, ...],
    tags_csv: str | None,
    new_type: str | None,
    new_status: str | None,
    new_summary: str | None,
    new_url: str | None,
    human: bool,
):
    """Update an item."""
    changes: dict[str, Any] = {}
    if new_content is not None:
        changes["content"] = new_content
    tag_list: list[str] = []
    if new_tags:
        tag_list += list(new_tags)
    if tags_csv is not None:
        tag_list += _split_tags(tags_csv)
    if new_tags or tags_csv is not None:
        changes["tags"] = tag_list
    if new_type:
        changes["type"] = new_type
    if new_status:
        changes["status"] = new_status
    if new_summary is not None:
        changes["summary"] = new_summary
    if new_url is not None:
        changes["bookmark_url"] = new_url

    if not changes:
        _print_err("no changes specified", code="NO_CHANGES")
        sys.exit(1)

    async def run(brain: ThinkTape) -> Item | None:
        return await brain.update(item_id, **changes)

    item = _run(run, ctx)
    if item is None:
        _print_err(f"item not found: {item_id}", code="NOT_FOUND")
        sys.exit(1)
    if human:
        click.echo(_human_item_detail(item))
    else:
        _print_json(_item_to_dict(item))


@cli.command()
@click.argument("item_id")
@click.option("--force", is_flag=True, help="Hard delete (remove files on disk).")
@click.pass_context
def delete(ctx: click.Context, item_id: str, force: bool):
    """Delete an item (soft by default, --force for hard delete)."""

    async def run(brain: ThinkTape) -> bool:
        existing = await brain.get(item_id)
        if existing is None:
            return False
        if force:
            await brain.index.delete(item_id)
            return await brain.store.hard_delete(item_id)
        return await brain.delete(item_id)

    ok = _run(run, ctx)
    if not ok:
        _print_err(f"item not found: {item_id}", code="NOT_FOUND")
        sys.exit(1)
    _print_json({"deleted": item_id, "hard": force})


# ============================== links / concepts ==============================


@cli.command(name="links")
@click.argument("item_id")
@click.option("--human", is_flag=True)
@click.pass_context
def links_cmd(ctx: click.Context, item_id: str, human: bool):
    """Show outgoing links and backlinks for an item."""

    async def run(brain: ThinkTape):
        existing = await brain.get(item_id)
        if existing is None:
            return None
        outgoing = await brain.get_links(item_id)
        backlinks = await brain.get_backlinks(item_id)
        return {"outgoing": outgoing, "backlinks": backlinks}

    result = _run(run, ctx)
    if result is None:
        _print_err(f"item not found: {item_id}", code="NOT_FOUND")
        sys.exit(1)
    if human:
        out = result["outgoing"]
        bl = result["backlinks"]
        if not out and not bl:
            click.echo("(no links)")
            return
        for link in out:
            if link["type"] == "concept":
                n = link.get("match_count", len(link.get("matches", [])))
                click.echo(f"  → [[{link['target']}]] ({n} matches)")
            else:
                tgt = link.get("item")
                if tgt:
                    snippet = (tgt["content"] or "").strip().replace("\n", " ")[:60]
                    click.echo(f"  → [[{link['target']}]] 直接关联  {snippet}")
                else:
                    click.echo(f"  → [[{link['target']}]] (item missing)")
        for b in bl:
            snippet = (b["content"] or "").strip().replace("\n", " ")[:60]
            click.echo(f"  ← {b['id']} 提到了 [[{b['link_text']}]]  {snippet}")
    else:
        _print_json(result)


@cli.command(name="concepts")
@click.option("--human", is_flag=True)
@click.pass_context
def concepts_cmd(ctx: click.Context, human: bool):
    """List all concepts used in [[]], with usage counts."""

    async def run(brain: ThinkTape):
        return await brain.all_concepts()

    concepts = _run(run, ctx)
    if human:
        if not concepts:
            click.echo("(no concepts)")
            return
        for c in concepts:
            click.echo(f"  [[{c['name']}]]  {c['count']}")
    else:
        _print_json({"concepts": concepts})


@cli.command(name="concept")
@click.argument("name")
@click.option("--human", is_flag=True)
@click.pass_context
def concept_cmd(ctx: click.Context, name: str, human: bool):
    """Find items referencing a concept (by [[concept]] or text match)."""

    async def run(brain: ThinkTape):
        return await brain.get_concept_items(name)

    items = _run(run, ctx)
    if human:
        if not items:
            click.echo(f"(no items mention “{name}”)")
            return
        for it in items:
            click.echo(_human_item_line(it))
    else:
        _print_json({"concept": name, "items": [_item_to_dict(i) for i in items], "total": len(items)})


# ============================== review ==============================


@cli.command(name="review")
@click.option("--today", "review_today", is_flag=True, help="Show today's digest.")
@click.option("--weekly", is_flag=True, help="Show this week's themes.")
@click.option("--random", "random_n", type=int, default=None,
              help="Show N random old items (Flomo-style recall).")
@click.option("--min-age-days", type=int, default=7, show_default=True,
              help="With --random: only items older than N days.")
@click.option("--llm/--no-llm", default=False, help="Use LLM for theme analysis.")
@click.option("--human", is_flag=True)
@click.pass_context
def review_cmd(
    ctx: click.Context,
    review_today: bool,
    weekly: bool,
    random_n: int | None,
    min_age_days: int,
    llm: bool,
    human: bool,
):
    """Generate review digests (today / weekly / random)."""
    config = ctx.obj["config"]
    from .review import ReviewEngine

    if not (review_today or weekly or random_n is not None):
        review_today = True

    async def run(brain: ThinkTape):
        engine = ReviewEngine(brain, config)
        out: dict[str, Any] = {}
        if review_today:
            out["today"] = await engine.daily_digest(use_llm=llm)
        if weekly:
            out["weekly"] = await engine.weekly_digest(use_llm=llm)
        if random_n is not None:
            out["random"] = await engine.random_recall(count=random_n, min_age_days=min_age_days)
        return out

    result = _run(run, ctx)
    if human:
        if "today" in result:
            d = result["today"]
            click.echo(f"📅 今日 ({d.get('date')})  {d.get('count', 0)} 条")
            if d.get("theme"):
                click.echo(f"   主题: {d['theme']}")
            if d.get("active_concepts"):
                click.echo("   概念: " + ", ".join(f"[[{c['name']}]] ×{c['count']}"
                                                  for c in d["active_concepts"][:5]))
            for it in d.get("items", [])[:10]:
                click.echo(_human_item_line(Item(**it)) if isinstance(it, dict) else _human_item_line(it))
        if "weekly" in result:
            w = result["weekly"]
            click.echo(f"\n📆 最近 7 天  {w.get('count', 0)} 条")
            if w.get("theme"):
                click.echo(f"   主题: {w['theme']}")
            if w.get("top_concepts"):
                click.echo("   高频概念: " + ", ".join(
                    f"[[{c['name']}]] ×{c['count']}" for c in w["top_concepts"][:5]))
        if "random" in result:
            r = result["random"]
            click.echo(f"\n🎲 随机回顾  {len(r.get('items', []))} 条")
            for it in r.get("items", []):
                click.echo(_human_item_line(Item(**it)) if isinstance(it, dict) else _human_item_line(it))
    else:
        _print_json(result)


# ============================== summarize ==============================


@cli.command()
@click.argument("item_id", required=False)
@click.option("--all", "all_items", is_flag=True, help="Summarize all items missing a summary.")
@click.option("--force", is_flag=True, help="Re-summarize items that already have a summary.")
@click.option("--limit", default=50, show_default=True, type=int,
              help="Max items to process with --all.")
@click.pass_context
def summarize(ctx: click.Context, item_id: str | None, all_items: bool, force: bool, limit: int):
    """Generate AI summary + auto-tags for one item or all pending items."""
    config = ctx.obj["config"]
    if not config.llm.enabled:
        _print_err("LLM disabled in config.toml ([llm].enabled = true)", code="LLM_DISABLED")
        sys.exit(1)

    from .summarize import Summarizer

    async def run(brain: ThinkTape):
        summarizer = Summarizer(config.llm)
        if item_id:
            item = await brain.get(item_id)
            if item is None:
                return {"error": "not_found", "id": item_id}
            result = await summarizer.summarize_and_tag(item.content)
            tags_merged = list(dict.fromkeys(item.tags + result.get("tags", [])))
            updated = await brain.update(
                item_id, summary=result.get("summary"), tags=tags_merged,
            )
            return {"updated": _item_to_dict(updated) if updated else None}
        if not all_items:
            return {"error": "specify item_id or --all"}
        # Process pending items
        items = await brain.list(status="active", limit=500)
        targets = [i for i in items if force or not i.summary]
        targets = [i for i in targets if i.content.strip()]
        targets = targets[:limit]
        processed = []
        for it in targets:
            try:
                r = await summarizer.summarize_and_tag(it.content)
                merged = list(dict.fromkeys(it.tags + r.get("tags", [])))
                await brain.update(it.id, summary=r.get("summary"), tags=merged)
                processed.append({"id": it.id, "summary": r.get("summary"), "tags": merged})
            except Exception as e:
                processed.append({"id": it.id, "error": str(e)})
        return {"processed": len(processed), "items": processed}

    result = _run(run, ctx)
    if "error" in result and not result.get("processed"):
        _print_err(result["error"], code="LLM_ERROR")
        sys.exit(1)
    _print_json(result)


# ============================== meta ==============================


@cli.command()
def version():
    """Show version."""
    _print_json({"version": _VERSION})


@cli.command(name="config")
@click.pass_context
def show_config(ctx: click.Context):
    """Show current configuration (sanitized)."""
    _print_json(_sanitize_config(ctx.obj["config"]))


# ============================== service ==============================


@cli.command()
@click.pass_context
def web(ctx: click.Context):
    """Start only the web server."""
    config = ctx.obj["config"]
    from .web import create_app

    app = create_app(config)
    uvicorn.run(app, host=config.web.host, port=config.web.port, log_level="info")


@cli.command(name="rebuild-index")
@click.pass_context
def rebuild_index(ctx: click.Context):
    """Rebuild the SQLite index from items/."""
    config = ctx.obj["config"]

    async def _run_rebuild():
        brain = ThinkTape(config)
        await brain.connect()
        try:
            n = await brain.rebuild_index()
            _print_json({"rebuilt": n})
        finally:
            await brain.close()

    asyncio.run(_run_rebuild())


@cli.command()
@click.pass_context
def serve(ctx: click.Context):
    """Start bot + web + transcriber + summarizer concurrently."""
    config = ctx.obj["config"]

    if config.telegram is None:
        click.echo("warning: telegram config missing — bot will not start", err=True)

    async def _run_serve():
        brain = ThinkTape(config)
        await brain.connect()

        from .transcribe import TranscribeQueue
        transcribe_queue = TranscribeQueue(brain)
        await transcribe_queue.start()

        summary_worker = None
        if config.llm.enabled:
            from .summarize import SummaryWorker
            summary_worker = SummaryWorker(brain, config.llm)
            await summary_worker.start()
            try:
                await summary_worker.backfill_pending()
            except Exception:
                logging.exception("summary backfill failed")

        bot = None
        if config.telegram is not None:
            from .bot import ThinkTapeBot
            bot = ThinkTapeBot(
                config, brain,
                transcribe_queue=transcribe_queue,
                summary_worker=summary_worker,
            )
            await bot.start()

        # Backfill any pending audio/video items that haven't been transcribed.
        try:
            n = await transcribe_queue.backfill_pending()
            if n:
                logging.info("queued %d items for transcription backfill", n)
        except Exception:
            logging.exception("backfill failed")

        from .web import create_app
        app = create_app(config, brain=brain, summary_worker=summary_worker)
        server_config = uvicorn.Config(
            app,
            host=config.web.host,
            port=config.web.port,
            log_level="info",
            lifespan="on",
        )
        server = uvicorn.Server(server_config)

        stop_event = asyncio.Event()

        def _signal_handler():
            stop_event.set()

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except NotImplementedError:
                pass

        server_task = asyncio.create_task(server.serve(), name="uvicorn")
        stop_task = asyncio.create_task(stop_event.wait(), name="stop-wait")

        done, _ = await asyncio.wait(
            [server_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if not server_task.done():
            server.should_exit = True
            await server_task

        await transcribe_queue.stop()
        if summary_worker is not None:
            await summary_worker.stop()
        if bot is not None:
            await bot.stop()
        await brain.close()

    asyncio.run(_run_serve())


# ============================== entry ==============================


def main() -> int:
    try:
        cli(obj={})
    except SystemExit:
        raise
    except Exception as e:
        _print_err(str(e), code="UNEXPECTED")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
