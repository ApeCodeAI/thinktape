"""Telegram Bot message handlers using Pyrogram."""

import asyncio
import functools
import logging
import shutil
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.handlers import DisconnectHandler
from pyrogram.types import Message

from braindump.config import get_config, get_timezone
from braindump.database import get_db, init_db

logger = logging.getLogger("braindump.bot")

# Download timeout in seconds (30 minutes)
DOWNLOAD_TIMEOUT = 1800

# Module-level bot status for health checks
_bot_connected = False
_bot_start_time: float | None = None
_last_message_time: float | None = None
_message_count: int = 0


def is_bot_connected() -> bool:
    return _bot_connected


def get_bot_status() -> dict:
    """Return bot status info for /status and /health."""
    import time as _time
    uptime = None
    if _bot_start_time is not None:
        uptime = _time.monotonic() - _bot_start_time
    return {
        "connected": _bot_connected,
        "uptime_seconds": round(uptime, 1) if uptime is not None else None,
        "last_message_time": _last_message_time,
        "message_count": _message_count,
    }


def _now() -> datetime:
    return datetime.now(get_timezone())


def _display_date(dt: datetime, boundary_hour: int) -> str:
    if dt.hour < boundary_hour:
        d = dt.date() - timedelta(days=1)
    else:
        d = dt.date()
    return d.isoformat()


def _media_dest(cfg, media_type: str, dt: datetime, source_id: str, ext: str) -> tuple[Path, str]:
    """Return (absolute_path, relative_path) for a media file.

    Directory placement uses display_date (respects day_boundary_hour),
    while the filename timestamp is the real created_at time.
    """
    ts = dt.strftime("%Y%m%d_%H%M%S")
    fname = f"{ts}_tg{source_id}.{ext}"
    display = _display_date(dt, cfg.general.day_boundary_hour)
    year, month, day = display.split("-")
    rel = f"media/{media_type}/{year}/{month}/{day}/{fname}"
    abs_path = cfg.data_dir / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    return abs_path, rel


def _format_size(size_bytes: int) -> str:
    """Format byte size to human readable string."""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024**3):.1f}GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024**2):.0f}MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f}KB"
    return f"{size_bytes}B"


def _check_disk_space(cfg, file_size: int | None) -> str | None:
    """Check if there's enough disk space for download.

    Returns an error message if space is insufficient, None if OK.
    If file_size is None (unknown), the check is skipped.
    """
    if file_size is None or file_size <= 0:
        return None
    try:
        usage = shutil.disk_usage(cfg.data_dir)
        required = int(file_size * 1.5)
        if usage.free < required:
            return (
                f"⚠️ 磁盘空间不足\n"
                f"需要: {_format_size(required)}\n"
                f"剩余: {_format_size(usage.free)}"
            )
    except OSError as e:
        logger.warning("Failed to check disk space: %s", e)
    return None


def _make_progress_callback(message: Message):
    """Create a progress callback for download_media.

    Updates the status message every 20% progress, with at least 3 seconds
    between updates to avoid Telegram API rate limiting.
    """
    state = {"last_update_time": 0.0, "last_percent": 0, "status_msg": None}

    async def progress(current: int, total: int):
        if total <= 0:
            return
        percent = int(current * 100 / total)
        # Only update at 20% intervals
        step = (percent // 20) * 20
        if step <= state["last_percent"] or step == 0:
            return
        # Rate limit: at least 3 seconds between updates
        now = time.monotonic()
        if now - state["last_update_time"] < 3.0:
            return

        state["last_percent"] = step
        state["last_update_time"] = now
        text = f"⬇️ 下载中... {step}% ({_format_size(current)}/{_format_size(total)})"
        try:
            if state["status_msg"] is None:
                state["status_msg"] = await message.reply_text(text, quote=True)
            else:
                await state["status_msg"].edit_text(text)
        except Exception as e:
            logger.debug("Progress update failed: %s", e)

    return progress, state


async def _download_with_timeout(message: Message, dest: Path, progress_cb=None) -> None:
    """Download media with timeout and cleanup on failure."""
    try:
        await asyncio.wait_for(
            message.download(file_name=str(dest), progress=progress_cb),
            timeout=DOWNLOAD_TIMEOUT,
        )
    except asyncio.TimeoutError:
        # Clean up partial file
        if dest.exists():
            dest.unlink()
        raise


def safe_handler(func):
    """Decorator that wraps bot handlers with error handling."""
    @functools.wraps(func)
    async def wrapper(client, message):
        global _last_message_time, _message_count
        try:
            await func(client, message)
            _last_message_time = time.time()
            _message_count += 1
        except FloodWait as e:
            logger.warning("FloodWait in %s: sleeping %d seconds", func.__name__, e.value)
            await asyncio.sleep(e.value + 1)
        except (ConnectionError, OSError) as e:
            # Network errors — don't try to reply (would likely fail too)
            logger.error("Network error in %s: %s", func.__name__, e, exc_info=True)
        except Exception as e:
            logger.error("Handler %s failed: %s", func.__name__, e, exc_info=True)
            try:
                await message.reply_text(f"❌ 保存失败: {e}")
            except Exception:
                pass  # reply also failed, already logged
    return wrapper


def create_bot(transcribe_worker=None, summary_worker=None) -> Client:
    """Create and configure the Pyrogram bot client."""
    global _bot_connected
    cfg = get_config()
    bot = Client(
        name="braindump_bot",
        api_id=cfg.telegram.api_id,
        api_hash=cfg.telegram.api_hash,
        bot_token=cfg.telegram.bot_token,
        workdir=str(cfg.data_dir),
    )

    allowed = set(cfg.telegram.allowed_users)

    def is_allowed(_, __, message: Message) -> bool:
        if not allowed:
            return True  # No restriction if list is empty
        return message.from_user and message.from_user.id in allowed

    allowed_filter = filters.create(is_allowed)

    @bot.on_message(allowed_filter & filters.command("start"))
    @safe_handler
    async def on_start(client: Client, message: Message):
        await message.reply_text(
            "**braindump** — dump your brain.\n\n"
            "Send me text, images, videos, or voice messages.\n"
            "Everything will be saved and searchable."
        )

    @bot.on_message(allowed_filter & filters.command("stats"))
    @safe_handler
    async def on_stats(client: Client, message: Message):
        db = await get_db()
        try:
            cursor = await db.execute("SELECT COUNT(*) FROM notes WHERE is_deleted = 0")
            total = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT media_type, COUNT(*) FROM notes WHERE is_deleted = 0 GROUP BY media_type"
            )
            by_type = await cursor.fetchall()
            lines = [f"Total notes: **{total}**\n"]
            for row in by_type:
                lines.append(f"  {row[0]}: {row[1]}")
            await message.reply_text("\n".join(lines))
        finally:
            await db.close()

    @bot.on_message(allowed_filter & filters.command("recent"))
    @safe_handler
    async def on_recent(client: Client, message: Message):
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id, created_at, media_type, substr(content, 1, 80) FROM notes "
                "WHERE is_deleted = 0 ORDER BY created_at DESC LIMIT 5"
            )
            rows = await cursor.fetchall()
            if not rows:
                await message.reply_text("No notes yet.")
                return
            lines = []
            for r in rows:
                preview = (r[3] or "").replace("\n", " ")
                lines.append(f"[{r[2]}] {r[1][:16]}\n  {preview}")
            await message.reply_text("\n\n".join(lines))
        finally:
            await db.close()

    @bot.on_message(allowed_filter & filters.command("status"))
    @safe_handler
    async def on_status(client: Client, message: Message):
        from braindump import __version__
        status = get_bot_status()

        lines = [f"**braindump** v{__version__}\n"]

        # Connection
        lines.append(f"Bot: {'connected' if status['connected'] else 'disconnected'}")

        # Uptime
        if status["uptime_seconds"] is not None:
            secs = int(status["uptime_seconds"])
            hours, remainder = divmod(secs, 3600)
            minutes, seconds = divmod(remainder, 60)
            if hours > 0:
                lines.append(f"Uptime: {hours}h {minutes}m {seconds}s")
            elif minutes > 0:
                lines.append(f"Uptime: {minutes}m {seconds}s")
            else:
                lines.append(f"Uptime: {seconds}s")

        # Message stats
        lines.append(f"Messages processed: {status['message_count']}")
        if status["last_message_time"]:
            from datetime import datetime
            last = datetime.fromtimestamp(status["last_message_time"], tz=get_timezone())
            lines.append(f"Last message: {last.strftime('%Y-%m-%d %H:%M:%S')}")

        # Worker queues
        if transcribe_worker:
            lines.append(f"Transcribe queue: {transcribe_worker.queue_size()}")
        if summary_worker:
            lines.append(f"Summary queue: {summary_worker.queue_size()}")

        await message.reply_text("\n".join(lines))

    @bot.on_message(allowed_filter & filters.text & ~filters.command(["start", "stats", "recent", "status"]))
    @safe_handler
    async def on_text(client: Client, message: Message):
        """Handle plain text messages."""
        cfg = get_config()
        now = _now()
        content = message.text or ""
        tags = _extract_tags(content)

        # Handle forwarded messages
        is_forwarded = 1 if message.forward_date else 0
        forward_from = None
        forward_date = None
        if message.forward_from:
            forward_from = message.forward_from.first_name or str(message.forward_from.id)
        elif message.forward_sender_name:
            forward_from = message.forward_sender_name
        if message.forward_date:
            forward_date = message.forward_date.replace(tzinfo=timezone.utc).astimezone(get_timezone()).isoformat()

        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(get_timezone())
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)

        # Write .md file with frontmatter
        from braindump.frontmatter import build_creation_frontmatter, render_frontmatter
        dest, rel = _media_dest(cfg, "text", created_at, str(message.id), "md")
        fm = build_creation_frontmatter(
            created_at=created_at.isoformat(),
            source="telegram",
            media_type="text",
            tags=tags,
        )
        dest.write_text(render_frontmatter(fm, content), encoding="utf-8")
        file_size = dest.stat().st_size

        # Trigger rule: text >= min_content_length → pending, else skipped
        summarize_status = (
            "pending" if len(content) >= cfg.llm.min_content_length else "skipped"
        )

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size, created_at, display_date, imported_at,
                    source, source_id, tags, is_forwarded, forward_from, forward_date,
                    transcribe_status, summarize_status)
                   VALUES (?, 'text', ?, ?, ?, ?, ?, 'telegram', ?, ?, ?, ?, ?, 'not_needed', ?)""",
                (content, rel, file_size, created_at.isoformat(), display_date, now.isoformat(),
                 str(message.id), ",".join(tags),
                 is_forwarded, forward_from, forward_date, summarize_status),
            )
            note_id = cursor.lastrowid
            await db.commit()
        finally:
            await db.close()

        if summary_worker and summarize_status == "pending":
            await summary_worker.enqueue(note_id)

        await message.reply_text("Saved.", quote=True)

    @bot.on_message(allowed_filter & filters.photo)
    @safe_handler
    async def on_photo(client: Client, message: Message):
        """Handle photo messages."""
        cfg = get_config()
        now = _now()
        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(get_timezone())
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        # Download photo
        dest, rel = _media_dest(cfg, "image", created_at, str(message.id), "jpg")
        await message.download(file_name=str(dest))

        file_size = dest.stat().st_size if dest.exists() else None

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size, created_at, display_date, imported_at,
                    source, source_id, tags, transcribe_status, summarize_status)
                   VALUES (?, 'image', ?, ?, ?, ?, ?, 'telegram', ?, ?, 'not_needed', 'skipped')""",
                (content, rel, file_size, created_at.isoformat(), display_date, now.isoformat(),
                 str(message.id), ",".join(tags)),
            )
            note_id = cursor.lastrowid
            await db.execute(
                "INSERT INTO attachments (note_id, file_path, media_type, file_size) VALUES (?, ?, 'image', ?)",
                (note_id, rel, file_size),
            )
            await db.commit()
        finally:
            await db.close()

        await message.reply_text("Image saved.", quote=True)

    @bot.on_message(allowed_filter & (filters.video | filters.video_note))
    @safe_handler
    async def on_video(client: Client, message: Message):
        """Handle video messages."""
        cfg = get_config()
        now = _now()
        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(get_timezone())
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        video = message.video or message.video_note
        ext = "mp4"
        duration = video.duration if video else None
        remote_size = video.file_size if video else None

        # Disk space check
        disk_err = _check_disk_space(cfg, remote_size)
        if disk_err:
            await message.reply_text(disk_err, quote=True)
            return

        dest, rel = _media_dest(cfg, "video", created_at, str(message.id), ext)

        # Download with progress and timeout
        progress_cb, progress_state = _make_progress_callback(message)
        try:
            await _download_with_timeout(message, dest, progress_cb)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ 下载超时（超过30分钟），请稍后重试。", quote=True)
            return

        file_size = dest.stat().st_size if dest.exists() else None

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size, duration,
                    created_at, display_date, imported_at,
                    source, source_id, tags, transcribe_status, summarize_status)
                   VALUES (?, 'video', ?, ?, ?, ?, ?, ?, 'telegram', ?, ?, 'pending', 'skipped')""",
                (content, rel, file_size, duration,
                 created_at.isoformat(), display_date, now.isoformat(),
                 str(message.id), ",".join(tags)),
            )
            note_id = cursor.lastrowid
            await db.execute(
                """INSERT INTO attachments
                   (note_id, file_path, media_type, file_size, duration)
                   VALUES (?, ?, 'video', ?, ?)""",
                (note_id, rel, file_size, duration),
            )
            await db.commit()
        finally:
            await db.close()

        if transcribe_worker:
            await transcribe_worker.enqueue(note_id, rel)
        await message.reply_text("Video saved. Transcription queued.", quote=True)

    @bot.on_message(allowed_filter & (filters.voice | filters.audio))
    @safe_handler
    async def on_voice(client: Client, message: Message):
        """Handle voice/audio messages."""
        cfg = get_config()
        now = _now()
        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(get_timezone())
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        audio = message.voice or message.audio
        ext = "ogg" if message.voice else (audio.file_name or "audio.mp3").split(".")[-1]
        duration = audio.duration if audio else None
        remote_size = audio.file_size if audio else None

        # Disk space check
        disk_err = _check_disk_space(cfg, remote_size)
        if disk_err:
            await message.reply_text(disk_err, quote=True)
            return

        dest, rel = _media_dest(cfg, "audio", created_at, str(message.id), ext)

        # Download with progress and timeout
        progress_cb, progress_state = _make_progress_callback(message)
        try:
            await _download_with_timeout(message, dest, progress_cb)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ 下载超时（超过30分钟），请稍后重试。", quote=True)
            return

        file_size = dest.stat().st_size if dest.exists() else None

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size, duration,
                    created_at, display_date, imported_at,
                    source, source_id, tags, transcribe_status, summarize_status)
                   VALUES (?, 'audio', ?, ?, ?, ?, ?, ?, 'telegram', ?, ?, 'pending', 'skipped')""",
                (content, rel, file_size, duration,
                 created_at.isoformat(), display_date, now.isoformat(),
                 str(message.id), ",".join(tags)),
            )
            note_id = cursor.lastrowid
            await db.execute(
                """INSERT INTO attachments
                   (note_id, file_path, media_type, file_size, duration)
                   VALUES (?, ?, 'audio', ?, ?)""",
                (note_id, rel, file_size, duration),
            )
            await db.commit()
        finally:
            await db.close()

        if transcribe_worker:
            await transcribe_worker.enqueue(note_id, rel)
        await message.reply_text("Voice saved. Transcription queued.", quote=True)

    @bot.on_message(allowed_filter & filters.document)
    @safe_handler
    async def on_document(client: Client, message: Message):
        """Handle document messages (try to detect media type)."""
        cfg = get_config()
        now = _now()
        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(get_timezone())
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        doc = message.document
        fname = doc.file_name or "file"
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "bin"
        remote_size = doc.file_size if doc else None

        # Classify by extension
        video_exts = {"mp4", "mov", "avi", "mkv", "webm"}
        audio_exts = {"mp3", "wav", "ogg", "m4a", "flac", "aac"}
        image_exts = {"jpg", "jpeg", "png", "gif", "webp", "heic"}

        if ext in video_exts:
            media_type = "video"
            transcribe_status = "pending"
            summarize_status = "skipped"  # will be set to 'pending' after transcription
        elif ext in audio_exts:
            media_type = "audio"
            transcribe_status = "pending"
            summarize_status = "skipped"  # will be set to 'pending' after transcription
        elif ext in image_exts:
            media_type = "image"
            transcribe_status = "not_needed"
            summarize_status = "skipped"
        else:
            media_type = "text"
            transcribe_status = "not_needed"
            summarize_status = "skipped"

        # Disk space check
        disk_err = _check_disk_space(cfg, remote_size)
        if disk_err:
            await message.reply_text(disk_err, quote=True)
            return

        dest, rel = _media_dest(cfg, media_type, created_at, str(message.id), ext)

        # Download with progress and timeout
        progress_cb, progress_state = _make_progress_callback(message)
        try:
            await _download_with_timeout(message, dest, progress_cb)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ 下载超时（超过30分钟），请稍后重试。", quote=True)
            return

        file_size = dest.stat().st_size if dest.exists() else None

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size,
                    created_at, display_date, imported_at,
                    source, source_id, tags, transcribe_status, summarize_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'telegram', ?, ?, ?, ?)""",
                (content, media_type, rel, file_size,
                 created_at.isoformat(), display_date, now.isoformat(),
                 str(message.id), ",".join(tags), transcribe_status, summarize_status),
            )
            note_id = cursor.lastrowid
            await db.execute(
                "INSERT INTO attachments (note_id, file_path, media_type, file_size) VALUES (?, ?, ?, ?)",
                (note_id, rel, media_type, file_size),
            )
            await db.commit()
        finally:
            await db.close()

        if transcribe_worker and transcribe_status == "pending":
            await transcribe_worker.enqueue(note_id, rel)
        await message.reply_text(f"File saved ({media_type}).", quote=True)

    # Register disconnect handler for connection state tracking
    async def on_disconnect(client):
        global _bot_connected
        logger.warning("Pyrogram disconnect event received")
        _bot_connected = False

    bot.add_handler(DisconnectHandler(on_disconnect))

    return bot


def _extract_tags(text: str) -> list[str]:
    """Extract #hashtags from text."""
    import re
    return list(dict.fromkeys(
        re.findall(r"(?:^|\s)#([a-zA-Z\u4e00-\u9fff][\w/\u4e00-\u9fff]*)", text)
    ))


async def run_bot():
    """Start the Telegram bot with its transcription and summary workers."""
    global _bot_connected, _bot_start_time

    from braindump.transcribe.engine import TranscribeWorker
    from braindump.llm.summarizer import SummaryWorker

    cfg = get_config()
    cfg.ensure_dirs()
    await init_db()

    transcribe = TranscribeWorker()
    summary = SummaryWorker()
    bot = create_bot(transcribe, summary)

    transcribe_task = asyncio.create_task(transcribe.run())
    summary_task = asyncio.create_task(summary.run())

    max_retries = 10
    base_delay = 5
    retries = 0

    logger.info("Starting Telegram bot...")
    try:
        while True:
            try:
                await bot.start()
                _bot_connected = True
                _bot_start_time = time.monotonic()
                logger.info("Bot connected. Press Ctrl+C to stop.")
                retries = 0

                while True:
                    await asyncio.sleep(60)
                    if not bot.is_connected:
                        logger.warning("Bot disconnected, will reconnect...")
                        break
            except FloodWait as e:
                logger.warning("FloodWait: sleeping %d seconds", e.value)
                await asyncio.sleep(e.value + 1)
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception as e:
                retries += 1
                if retries > max_retries:
                    logger.error("Max retries (%d) reached, giving up", max_retries)
                    raise
                delay = min(base_delay * (2 ** (retries - 1)), 300)
                logger.error(
                    "Bot error (retry %d/%d in %ds): %s",
                    retries, max_retries, delay, e,
                )
                await asyncio.sleep(delay)
            finally:
                _bot_connected = False
                try:
                    await bot.stop()
                except Exception:
                    pass
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        transcribe.stop()
        summary.stop()
        transcribe_task.cancel()
        summary_task.cancel()
