"""CLI entry point: python -m braindump"""

import argparse
import asyncio
import logging
import sys

from braindump import __version__, setup_logging

logger = logging.getLogger("braindump")


# Module-level reference for health checks
_transcribe_worker = None


def get_transcribe_worker():
    return _transcribe_worker


async def _serve_all():
    """Start Web + Bot + Transcribe Worker concurrently using TaskGroup."""
    global _transcribe_worker
    import uvicorn
    from braindump.config import get_config
    from braindump.database import init_db
    from braindump.bot.handlers import create_bot
    from braindump.transcribe.engine import TranscribeWorker, cleanup_old_tmp_files
    from braindump.web.app import create_app

    cfg = get_config()
    cfg.ensure_dirs()

    # Log version + config summary at startup (mask sensitive values)
    logger.info("braindump v%s starting", __version__)
    logger.info("  data_dir: %s", cfg.data_dir)
    logger.info("  web: %s:%d", cfg.web.host, cfg.web.port)
    logger.info("  transcribe engine: %s", cfg.transcribe.engine)
    logger.info("  timezone: %s", cfg.general.timezone)
    if cfg.telegram.bot_token:
        logger.info("  telegram bot: configured")
    else:
        logger.warning("  telegram bot: not configured")

    # Clean up orphaned temp files from previous runs
    cleanup_old_tmp_files(cfg)

    await init_db()

    worker = TranscribeWorker()
    _transcribe_worker = worker
    bot = create_bot(worker)
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


def main():
    setup_logging()

    parser = argparse.ArgumentParser(prog="braindump", description="Personal expression material library")
    sub = parser.add_subparsers(dest="command")

    # serve
    sub.add_parser("serve", help="Start all services (Bot + Web + Transcribe Worker)")

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


if __name__ == "__main__":
    main()
