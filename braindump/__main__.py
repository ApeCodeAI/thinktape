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


def get_transcribe_worker():
    return _transcribe_worker


def get_summary_worker():
    return _summary_worker


async def _serve_all():
    """Start Web + Bot + Transcribe Worker + Summary Worker concurrently."""
    global _transcribe_worker, _summary_worker
    import uvicorn
    from braindump.config import get_config, validate_llm_config
    from braindump.database import init_db
    from braindump.bot.handlers import create_bot
    from braindump.transcribe.engine import TranscribeWorker, cleanup_old_tmp_files
    from braindump.llm.summarizer import SummaryWorker
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

    config = uvicorn.Config(
        app,
        host=cfg.web.host,
        port=cfg.web.port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    async def run_bot_task():
        import braindump.bot.handlers as bot_mod
        await bot.start()
        bot_mod._bot_connected = True
        logger.info("Bot is running.")
        try:
            await asyncio.Event().wait()
        finally:
            bot_mod._bot_connected = False
            await bot.stop()

    # TaskGroup: if any task crashes, all are cancelled → main exits → Docker restarts
    async with asyncio.TaskGroup() as tg:
        tg.create_task(server.serve())
        tg.create_task(run_bot_task())
        tg.create_task(worker.run())
        tg.create_task(summary.run())


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


def main():
    setup_logging()

    parser = argparse.ArgumentParser(prog="braindump", description="Personal expression material library")
    sub = parser.add_subparsers(dest="command")

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
    sub.add_parser("stats", help="Show statistics")

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

    # summarize --backfill
    sum_p = sub.add_parser("summarize", help="Summarization utilities")
    sum_p.add_argument("--backfill", action="store_true", help="Mark historical notes for summarization")
    sum_p.add_argument("--min-length", type=int, default=50, help="Minimum content length for backfill (default: 50)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "web":
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
            for exc in eg.exceptions:
                logger.error("Service crashed: %s", exc, exc_info=exc)
            sys.exit(1)

    elif args.command == "upgrade":
        from braindump.database import run_migrations
        asyncio.run(run_migrations())

    elif args.command == "stats":
        from braindump.database import show_stats
        asyncio.run(show_stats())

    elif args.command == "rebuild-index":
        from braindump.database import rebuild_index
        asyncio.run(rebuild_index())

    elif args.command == "retry-summary":
        asyncio.run(_retry_summary(args.all_failed, args.note_id))

    elif args.command == "retry-transcribe":
        asyncio.run(_retry_transcribe(args.all_failed, args.note_id))

    elif args.command == "summarize":
        if args.backfill:
            asyncio.run(_summarize_backfill(args.min_length))
        else:
            sum_p.print_help()


if __name__ == "__main__":
    main()
