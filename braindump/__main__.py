"""CLI entry point: python -m braindump"""

import argparse
import asyncio
import sys


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
        from braindump.web.app import run_web
        run_web()

    elif args.command == "upgrade":
        from braindump.database import run_migrations
        asyncio.run(run_migrations())

    elif args.command == "stats":
        from braindump.database import show_stats
        asyncio.run(show_stats())


if __name__ == "__main__":
    main()
