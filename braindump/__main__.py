"""CLI entry point: python -m braindump"""

import argparse
import asyncio
import sys


async def _serve_all():
    """Start Web + Bot + Transcribe Worker concurrently."""
    import uvicorn
    from telegram import Update
    from braindump.config import get_config
    from braindump.database import init_db
    from braindump.bot.handlers import create_app as create_bot_app
    from braindump.transcribe.engine import TranscribeWorker
    from braindump.web.app import create_app

    cfg = get_config()
    cfg.ensure_dirs()
    await init_db()

    worker = TranscribeWorker()
    bot_app = create_bot_app(worker)
    app = create_app()

    config = uvicorn.Config(
        app,
        host=cfg.web.host,
        port=cfg.web.port,
        log_level="info",
    )
    server = uvicorn.Server(config)

    async def run_bot_task():
        await bot_app.initialize()
        await bot_app.start()
        await bot_app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        print("Bot is running.")
        try:
            await asyncio.Event().wait()
        finally:
            await bot_app.updater.stop()
            await bot_app.stop()
            await bot_app.shutdown()

    tasks = [
        asyncio.create_task(server.serve()),
        asyncio.create_task(run_bot_task()),
        asyncio.create_task(worker.run()),
    ]

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        worker.stop()
        for t in tasks:
            t.cancel()


def main():
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
        asyncio.run(_serve_all())

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
