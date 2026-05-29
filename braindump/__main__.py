"""CLI entry point: python -m braindump"""

import argparse
import asyncio
import logging
import sys

from braindump import __version__, setup_logging

logger = logging.getLogger("braindump")


# Module-level references for health checks
_transcribe_worker = None
_summary_worker = None
_review_scheduler = None


def get_transcribe_worker():
    return _transcribe_worker


def get_summary_worker():
    return _summary_worker


def get_review_scheduler():
    return _review_scheduler


async def _serve_all():
    """Start Web + Bot + Transcribe Worker + Summary Worker + Review concurrently."""
    global _transcribe_worker, _summary_worker, _review_scheduler
    import uvicorn
    from braindump.config import get_config, validate_llm_config
    from braindump.database import init_db
    from braindump.bot.handlers import create_bot
    from braindump.transcribe.engine import TranscribeWorker, cleanup_old_tmp_files
    from braindump.llm.summarizer import SummaryWorker
    from braindump.review.scheduler import ReviewScheduler
    from braindump.web.app import create_app

    cfg = get_config()
    cfg.ensure_dirs()

    # Validate LLM config (warn and disable if API key missing)
    validate_llm_config(cfg)

    # Log version + config summary at startup (mask sensitive values)
    logger.info("braindump v%s starting", __version__)
    logger.info("  data_dir: %s", cfg.data_dir)
    logger.info("  web: %s:%d", cfg.web.host, cfg.web.port)
    logger.info("  transcribe engine: %s", cfg.transcribe.engine)
    logger.info("  llm: %s (model: %s)", "enabled" if cfg.llm.enabled else "disabled", cfg.llm.model)
    logger.info("  timezone: %s", cfg.general.timezone)
    logger.info(
        "  review: %s (%s, %d notes)",
        "enabled" if cfg.review.enabled else "disabled",
        cfg.review.schedule,
        cfg.review.count,
    )
    if cfg.telegram.bot_token:
        logger.info("  telegram bot: configured")
    else:
        logger.warning("  telegram bot: not configured")

    # Clean up orphaned temp files from previous runs
    cleanup_old_tmp_files(cfg)

    await init_db()

    summary = SummaryWorker()
    _summary_worker = summary

    worker = TranscribeWorker(summary_worker=summary)
    _transcribe_worker = worker

    bot = create_bot(worker, summary)
    app = create_app()

    review = ReviewScheduler(cfg, bot)
    _review_scheduler = review

    config = uvicorn.Config(
        app,
        host=cfg.web.host,
        port=cfg.web.port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    async def run_bot_task():
        import time as _time
        import braindump.bot.handlers as bot_mod
        from pyrogram.errors import FloodWait

        max_retries = 10
        base_delay = 5  # seconds
        retries = 0

        while True:
            try:
                await bot.start()
                bot_mod._bot_connected = True
                bot_mod._bot_start_time = _time.monotonic()
                logger.info("Bot connected successfully.")
                retries = 0  # reset on successful connection

                # Monitor connection with periodic ping
                while True:
                    await asyncio.sleep(60)
                    if not bot.is_connected:
                        logger.warning("Bot disconnected, will reconnect...")
                        break
            except FloodWait as e:
                logger.warning("FloodWait: sleeping %d seconds", e.value)
                await asyncio.sleep(e.value + 1)
            except Exception as e:
                retries += 1
                if retries > max_retries:
                    logger.error("Max retries (%d) reached, giving up", max_retries)
                    raise
                delay = min(base_delay * (2 ** (retries - 1)), 300)  # max 5 min
                logger.error(
                    "Bot error (retry %d/%d in %ds): %s",
                    retries, max_retries, delay, e,
                )
                await asyncio.sleep(delay)
            finally:
                bot_mod._bot_connected = False
                try:
                    await bot.stop()
                except Exception:
                    pass

    # TaskGroup: if any task crashes, all are cancelled → main exits → Docker restarts
    async with asyncio.TaskGroup() as tg:
        tg.create_task(server.serve(), name="web")
        tg.create_task(run_bot_task(), name="bot")
        tg.create_task(worker.run(), name="transcribe")
        tg.create_task(summary.run(), name="summary")
        tg.create_task(review.run(), name="review")


# ── CLI commands for retry/backfill ─────────────────────────────

async def _retry_summary(all_failed: bool, note_id: int | None):
    """Reset failed summaries to pending so SummaryWorker can re-process."""
    from braindump.database import init_db, get_db

    await init_db()
    db = await get_db()
    try:
        if note_id is not None:
            cursor = await db.execute(
                "UPDATE notes SET summarize_status = 'pending' WHERE id = ? AND summarize_status = 'failed'",
                (note_id,),
            )
        elif all_failed:
            cursor = await db.execute(
                "UPDATE notes SET summarize_status = 'pending' WHERE summarize_status = 'failed'"
            )
        else:
            logger.error("Specify --all or --note-id")
            return
        await db.commit()
        logger.info("Reset %d note(s) to pending for re-summarization", cursor.rowcount)
    finally:
        await db.close()


async def _retry_transcribe(all_failed: bool, note_id: int | None):
    """Reset failed transcriptions to pending."""
    from braindump.database import init_db, get_db

    await init_db()
    db = await get_db()
    try:
        if note_id is not None:
            cursor = await db.execute(
                "UPDATE notes SET transcribe_status = 'pending' WHERE id = ? AND transcribe_status = 'failed'",
                (note_id,),
            )
        elif all_failed:
            cursor = await db.execute(
                "UPDATE notes SET transcribe_status = 'pending' WHERE transcribe_status = 'failed'"
            )
        else:
            logger.error("Specify --all or --note-id")
            return
        await db.commit()
        logger.info("Reset %d note(s) to pending for re-transcription", cursor.rowcount)
    finally:
        await db.close()


async def _summarize_backfill(min_length: int):
    """Set historical notes to pending for summarization (backfill)."""
    from braindump.database import init_db, get_db

    await init_db()
    db = await get_db()
    try:
        # Text notes with enough content that haven't been summarized
        cursor = await db.execute(
            """UPDATE notes SET summarize_status = 'pending'
               WHERE summarize_status IN ('skipped', 'failed')
                 AND is_deleted = 0
                 AND (
                   (media_type = 'text' AND length(content) >= ?)
                   OR (media_type IN ('audio', 'video') AND transcript IS NOT NULL AND length(transcript) >= ?)
                 )""",
            (min_length, min_length),
        )
        await db.commit()
        logger.info("Marked %d note(s) for backfill summarization", cursor.rowcount)
    finally:
        await db.close()


async def _migrate_frontmatter():
    """Write frontmatter to all existing .md files from database metadata."""
    from braindump.config import get_config
    from braindump.database import init_db, get_db
    from braindump.frontmatter import (
        build_creation_frontmatter,
        build_summary_frontmatter,
        write_frontmatter_to_file,
        parse_frontmatter,
    )

    cfg = get_config()
    await init_db()
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT id, file_path, created_at, source, media_type, tags,
                      ai_title, ai_summary, ai_tags, ai_mood, summarize_status
               FROM notes
               WHERE is_deleted = 0 AND media_type = 'text' AND file_path IS NOT NULL"""
        )
        rows = await cursor.fetchall()
    finally:
        await db.close()

    updated = 0
    skipped = 0
    for row in rows:
        note = dict(row)
        file_path = note["file_path"]
        if not file_path or not file_path.endswith(".md"):
            continue

        abs_path = cfg.data_dir / file_path
        if not abs_path.exists():
            logger.warning("File not found: %s (note #%d)", abs_path, note["id"])
            continue

        # Check if already has frontmatter
        text = abs_path.read_text(encoding="utf-8")
        existing_meta, _ = parse_frontmatter(text)

        # Build creation frontmatter
        user_tags = [t.strip() for t in (note["tags"] or "").split(",") if t.strip()]
        fm = build_creation_frontmatter(
            created_at=note["created_at"],
            source=note["source"],
            media_type=note["media_type"],
            tags=user_tags,
        )

        # Add summary fields if available
        if note["summarize_status"] == "done" and note["ai_title"]:
            summary_fm = build_summary_frontmatter(
                ai_title=note["ai_title"],
                ai_tags_json=note["ai_tags"] or "",
                ai_mood=note["ai_mood"] or "",
                ai_summary=note["ai_summary"] or "",
            )
            fm.update(summary_fm)
            # Special merge for tags
            if "tags" in summary_fm and "tags" in fm:
                seen = set()
                combined = []
                for t in user_tags + (summary_fm.get("tags") or []):
                    if t not in seen:
                        seen.add(t)
                        combined.append(t)
                fm["tags"] = combined

        if existing_meta:
            # Already has frontmatter — merge
            from braindump.frontmatter import merge_frontmatter
            fm = merge_frontmatter(existing_meta, fm)

        write_frontmatter_to_file(abs_path, fm)
        updated += 1

    logger.info("migrate-frontmatter complete: %d updated, %d skipped", updated, skipped)


def main():
    setup_logging()

    parser = argparse.ArgumentParser(prog="braindump", description="Personal expression material library")
    sub = parser.add_subparsers(dest="command")

    # init
    init_p = sub.add_parser("init", help="Initialize data directory, config, and database")
    init_p.add_argument("--data-dir", default=None, help="Data directory (default: ~/braindump-data)")
    init_p.add_argument("--force", action="store_true", help="Overwrite config.toml if it already exists")
    init_p.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    # add
    add_p = sub.add_parser("add", help="Create a text note from CLI")
    add_p.add_argument("text", nargs="?", help="Text content. Use --stdin to read from stdin")
    add_p.add_argument("--stdin", action="store_true", help="Read note content from stdin")
    add_p.add_argument("--tag", action="append", default=[], help="Add a tag (repeatable)")
    add_p.add_argument("--tags", default="", help="Comma-separated tags")
    add_p.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    # list
    list_p = sub.add_parser("list", help="List recent notes")
    list_p.add_argument("--limit", type=int, default=20)
    list_p.add_argument("--offset", type=int, default=0)
    list_p.add_argument("--type", dest="media_type", default=None, help="Filter by media type")
    list_p.add_argument("--tag", default=None, help="Filter by tag")
    list_p.add_argument("--q", default=None, help="Full-text search query")
    list_p.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    # search
    search_p = sub.add_parser("search", help="Search notes")
    search_p.add_argument("query", help="Search query")
    search_p.add_argument("--limit", type=int, default=20)
    search_p.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    # show
    show_p = sub.add_parser("show", help="Show a note")
    show_p.add_argument("note_id", type=int)
    show_p.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    # serve
    sub.add_parser("serve", help="Start all services (Bot + Web + Transcribe + Summary)")

    # web
    web_p = sub.add_parser("web", help="Start Web UI only")
    web_p.add_argument("--host", default=None)
    web_p.add_argument("--port", type=int, default=None)

    # import
    import_p = sub.add_parser("import", help="Import data")
    import_sub = import_p.add_subparsers(dest="import_type")
    flomo_p = import_sub.add_parser("flomo", help="Import from Flomo HTML export")
    flomo_p.add_argument("path", help="Path to Flomo export directory")

    # bot
    sub.add_parser("bot", help="Start Telegram Bot only")

    # stats
    stats_p = sub.add_parser("stats", help="Show statistics")
    stats_p.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    # upgrade
    sub.add_parser("upgrade", help="Run database migrations")

    # rebuild-index
    sub.add_parser("rebuild-index", help="Rebuild database from filesystem")

    # retry-summary
    retry_sum_p = sub.add_parser("retry-summary", help="Reset failed summaries to pending")
    retry_sum_p.add_argument("--all", action="store_true", dest="all_failed", help="Reset all failed summaries")
    retry_sum_p.add_argument("--note-id", type=int, default=None, help="Reset a specific note")

    # retry-transcribe
    retry_tr_p = sub.add_parser("retry-transcribe", help="Reset failed transcriptions to pending")
    retry_tr_p.add_argument("--all", action="store_true", dest="all_failed", help="Reset all failed transcriptions")
    retry_tr_p.add_argument("--note-id", type=int, default=None, help="Reset a specific note")

    # migrate-frontmatter
    sub.add_parser("migrate-frontmatter", help="Write frontmatter to existing .md files from DB metadata")

    # summarize --backfill
    sum_p = sub.add_parser("summarize", help="Summarization utilities")
    sum_p.add_argument("--backfill", action="store_true", help="Mark historical notes for summarization")
    sum_p.add_argument("--min-length", type=int, default=50, help="Minimum content length for backfill (default: 50)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        from pathlib import Path
        from braindump.cli import emit, init_project

        result = asyncio.run(init_project(Path(args.data_dir) if args.data_dir else None, force=args.force))
        emit(
            result,
            args.json,
            [
                f"Initialized braindump data dir: {result['data_dir']}",
                f"Config: {result['config_path']}",
                f"Database: {result['db_path']}",
                "Next: braindump add \"your thought\" --json",
            ],
        )

    elif args.command == "add":
        from braindump.cli import add_text_note, emit, read_stdin_or_arg

        try:
            content = read_stdin_or_arg(args.text, args.stdin)
            result = asyncio.run(add_text_note(content, args.tag, args.tags))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)
        emit(
            result,
            args.json,
            [
                f"Saved note #{result['id']}",
                f"File: {result['file_path']}",
            ],
        )

    elif args.command == "list":
        from braindump.cli import emit, list_notes

        result = asyncio.run(
            list_notes(
                limit=args.limit,
                offset=args.offset,
                media_type=args.media_type,
                tag=args.tag,
                query=args.q,
            )
        )
        emit(
            result,
            args.json,
            [
                f"{note['id']}\t{note['created_at']}\t{note['type']}\t{note['title']}"
                for note in result["notes"]
            ],
        )

    elif args.command == "search":
        from braindump.cli import emit, search_notes

        result = asyncio.run(search_notes(args.query, limit=args.limit))
        emit(
            result,
            args.json,
            [
                f"{note['id']}\t{note['created_at']}\t{note['type']}\t{note['title']}"
                for note in result["notes"]
            ],
        )

    elif args.command == "show":
        from braindump.cli import emit, show_note

        try:
            result = asyncio.run(show_note(args.note_id))
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(3)
        note = result["note"]
        content = note.get("content") or note.get("transcript") or ""
        emit(
            result,
            args.json,
            [
                f"#{note['id']} {note['created_at']} [{note['media_type']}]",
                content,
            ],
        )

    elif args.command == "web":
        from braindump.web.app import run_web
        run_web(host=args.host, port=args.port)

    elif args.command == "import":
        if args.import_type == "flomo":
            from braindump.importer.flomo import import_flomo
            asyncio.run(import_flomo(args.path))
        else:
            import_p.print_help()

    elif args.command == "bot":
        from braindump.bot.handlers import run_bot
        asyncio.run(run_bot())

    elif args.command == "serve":
        try:
            asyncio.run(_serve_all())
        except* KeyboardInterrupt:
            logger.info("Shutting down...")
        except* Exception as eg:
            from pyrogram.errors import FloodWait
            for exc in eg.exceptions:
                if isinstance(exc, FloodWait):
                    logger.error("Service crashed due to Telegram FloodWait (%ds): %s", exc.value, exc)
                elif isinstance(exc, (ConnectionError, OSError)):
                    logger.error("Service crashed due to network error: %s", exc, exc_info=exc)
                else:
                    logger.error("Service crashed: %s", exc, exc_info=exc)
            sys.exit(1)

    elif args.command == "upgrade":
        from braindump.database import run_migrations
        asyncio.run(run_migrations())

    elif args.command == "stats":
        if args.json:
            from braindump.cli import emit
            from braindump.database import get_stats

            emit(asyncio.run(get_stats()), True)
        else:
            from braindump.database import show_stats
            asyncio.run(show_stats())

    elif args.command == "rebuild-index":
        from braindump.database import rebuild_index
        asyncio.run(rebuild_index())

    elif args.command == "retry-summary":
        asyncio.run(_retry_summary(args.all_failed, args.note_id))

    elif args.command == "retry-transcribe":
        asyncio.run(_retry_transcribe(args.all_failed, args.note_id))

    elif args.command == "migrate-frontmatter":
        asyncio.run(_migrate_frontmatter())

    elif args.command == "summarize":
        if args.backfill:
            asyncio.run(_summarize_backfill(args.min_length))
        else:
            sum_p.print_help()


if __name__ == "__main__":
    main()
