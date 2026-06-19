"""braindump CLI."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import click
import uvicorn

from .config import load_config
from .core import BrainDump


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("pyrogram").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


@click.group()
@click.option("--log-level", default="INFO", show_default=True)
@click.pass_context
def cli(ctx: click.Context, log_level: str):
    """braindump v2 — personal dump tool."""
    _setup_logging(log_level)
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()


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

    async def _run():
        brain = BrainDump(config)
        await brain.connect()
        try:
            n = await brain.rebuild_index()
            click.echo(f"rebuilt {n} items")
        finally:
            await brain.close()

    asyncio.run(_run())


@cli.command()
@click.pass_context
def serve(ctx: click.Context):
    """Start bot + web + transcriber concurrently."""
    config = ctx.obj["config"]

    if config.telegram is None:
        click.echo("warning: telegram config missing — bot will not start", err=True)

    async def _run():
        brain = BrainDump(config)
        await brain.connect()

        from .transcribe import TranscribeQueue
        transcribe_queue = TranscribeQueue(brain)
        await transcribe_queue.start()

        bot = None
        if config.telegram is not None:
            from .bot import BrainDumpBot
            bot = BrainDumpBot(config, brain, transcribe_queue=transcribe_queue)
            await bot.start()

        # Backfill any pending audio/video items that haven't been transcribed.
        try:
            n = await transcribe_queue.backfill_pending()
            if n:
                logging.info("queued %d items for transcription backfill", n)
        except Exception:
            logging.exception("backfill failed")

        from .web import create_app
        app = create_app(config, brain=brain)
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
                # Windows
                pass

        server_task = asyncio.create_task(server.serve(), name="uvicorn")
        stop_task = asyncio.create_task(stop_event.wait(), name="stop-wait")

        done, _ = await asyncio.wait(
            [server_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Trigger shutdown
        if not server_task.done():
            server.should_exit = True
            await server_task

        await transcribe_queue.stop()
        if bot is not None:
            await bot.stop()
        await brain.close()

    asyncio.run(_run())


def main() -> int:
    cli(obj={})
    return 0


if __name__ == "__main__":
    sys.exit(main())
