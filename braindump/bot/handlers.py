"""Telegram Bot message handlers using python-telegram-bot v20+."""

import asyncio
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from braindump.config import get_config, get_timezone
from braindump.database import get_db, init_db


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


def _extract_tags(text: str) -> list[str]:
    """Extract #hashtags from text."""
    return list(dict.fromkeys(
        re.findall(r"(?:^|\s)#([a-zA-Z\u4e00-\u9fff][\w/\u4e00-\u9fff]*)", text)
    ))


def _parse_created_at(message) -> datetime:
    """Get message creation time in configured timezone."""
    now = _now()
    dt = message.date or now
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(get_timezone())


def _parse_forward(message) -> tuple[int, str | None, str | None]:
    """Extract forward info from a message. Returns (is_forwarded, forward_from, forward_date)."""
    origin = message.forward_origin
    if origin is None:
        return 0, None, None

    forward_from = None
    forward_date = None

    # forward_origin.date is the original send date
    if hasattr(origin, "date") and origin.date:
        fd = origin.date
        if fd.tzinfo is None:
            fd = fd.replace(tzinfo=timezone.utc)
        forward_date = fd.astimezone(get_timezone()).isoformat()

    # origin type can be MessageOriginUser, MessageOriginHiddenUser, MessageOriginChannel, etc.
    origin_type = origin.type
    if origin_type == "user" and hasattr(origin, "sender_user") and origin.sender_user:
        forward_from = origin.sender_user.first_name or str(origin.sender_user.id)
    elif origin_type == "hidden_user" and hasattr(origin, "sender_user_name"):
        forward_from = origin.sender_user_name
    elif origin_type == "channel" and hasattr(origin, "chat"):
        forward_from = origin.chat.title or str(origin.chat.id)

    return 1, forward_from, forward_date


# ── Media group collector ──────────────────────────────────────────────
# When users send multiple photos at once, Telegram delivers them as
# separate messages sharing the same media_group_id.  We collect them
# and flush once a short timeout elapses with no new message for that group.

_media_groups: dict[str, list] = {}
_media_group_timers: dict[str, asyncio.TimerHandle] = {}
_MEDIA_GROUP_TIMEOUT = 1.5  # seconds


async def _flush_media_group(group_id: str, context: ContextTypes.DEFAULT_TYPE):
    """Process a collected media group."""
    messages = _media_groups.pop(group_id, [])
    _media_group_timers.pop(group_id, None)
    if not messages:
        return

    cfg = get_config()
    first = messages[0]
    created_at = _parse_created_at(first)
    display_date = _display_date(created_at, cfg.general.day_boundary_hour)
    now = _now()
    content = first.caption or ""
    tags = _extract_tags(content)
    is_forwarded, forward_from, forward_date = _parse_forward(first)

    # Download all photos
    attachments = []
    first_rel = None
    first_size = None
    for msg in messages:
        photo = msg.photo[-1]  # highest resolution
        dest, rel = _media_dest(cfg, "image", created_at, str(msg.message_id), "jpg")
        file_obj = await photo.get_file()
        await file_obj.download_to_drive(str(dest))
        file_size = dest.stat().st_size if dest.exists() else None
        attachments.append((rel, file_size))
        if first_rel is None:
            first_rel, first_size = rel, file_size

    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO notes
               (content, media_type, file_path, file_size, created_at, display_date, imported_at,
                source, source_id, tags, is_forwarded, forward_from, forward_date,
                transcribe_status)
               VALUES (?, 'image', ?, ?, ?, ?, ?, 'telegram', ?, ?, ?, ?, ?, 'not_needed')""",
            (content, first_rel, first_size, created_at.isoformat(), display_date, now.isoformat(),
             str(first.message_id), ",".join(tags),
             is_forwarded, forward_from, forward_date),
        )
        note_id = cursor.lastrowid
        for idx, (rel, fsize) in enumerate(attachments):
            await db.execute(
                "INSERT INTO attachments (note_id, file_path, media_type, file_size, sort_order) VALUES (?, ?, 'image', ?, ?)",
                (note_id, rel, fsize, idx),
            )
        await db.commit()
    finally:
        await db.close()

    await first.reply_text(f"{len(attachments)} images saved.", quote=True)


def _allowed_user_filter() -> filters.BaseFilter:
    """Build a filter that only allows configured user IDs."""
    cfg = get_config()
    allowed = set(cfg.telegram.allowed_users)
    if not allowed:
        return filters.ALL
    return filters.User(user_id=list(allowed))


def create_app(transcribe_worker=None) -> Application:
    """Create and configure the PTB Application."""
    cfg = get_config()
    application = Application.builder().token(cfg.telegram.bot_token).build()

    allowed = _allowed_user_filter()

    # ── Commands ────────────────────────────────────────────────────────

    async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "**braindump** — dump your brain.\n\n"
            "Send me text, images, videos, or voice messages.\n"
            "Everything will be saved and searchable.",
            parse_mode="Markdown",
        )

    async def on_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db = await get_db()
        try:
            cursor = await db.execute("SELECT COUNT(*) FROM notes WHERE is_deleted = 0")
            total = (await cursor.fetchone())[0]
            cursor = await db.execute(
                "SELECT media_type, COUNT(*) FROM notes WHERE is_deleted = 0 GROUP BY media_type"
            )
            by_type = await cursor.fetchall()
            lines = [f"Total notes: *{total}*\n"]
            for row in by_type:
                lines.append(f"  {row[0]}: {row[1]}")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        finally:
            await db.close()

    async def on_recent(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id, created_at, media_type, substr(content, 1, 80) FROM notes "
                "WHERE is_deleted = 0 ORDER BY created_at DESC LIMIT 5"
            )
            rows = await cursor.fetchall()
            if not rows:
                await update.message.reply_text("No notes yet.")
                return
            lines = []
            for r in rows:
                preview = (r[3] or "").replace("\n", " ")
                lines.append(f"[{r[2]}] {r[1][:16]}\n  {preview}")
            await update.message.reply_text("\n\n".join(lines))
        finally:
            await db.close()

    async def on_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT transcribe_status, COUNT(*) FROM notes "
                "WHERE transcribe_status != 'not_needed' GROUP BY transcribe_status"
            )
            rows = await cursor.fetchall()
            if not rows:
                await update.message.reply_text("No transcription tasks.")
                return
            lines = ["Transcription status:"]
            for status, count in rows:
                lines.append(f"  {status}: {count}")
            await update.message.reply_text("\n".join(lines))
        finally:
            await db.close()

    application.add_handler(CommandHandler("start", on_start, filters=allowed))
    application.add_handler(CommandHandler("stats", on_stats, filters=allowed))
    application.add_handler(CommandHandler("recent", on_recent, filters=allowed))
    application.add_handler(CommandHandler("status", on_status, filters=allowed))

    # ── Text messages ───────────────────────────────────────────────────

    async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        cfg = get_config()
        now = _now()
        content = message.text or ""
        tags = _extract_tags(content)
        created_at = _parse_created_at(message)
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        is_forwarded, forward_from, forward_date = _parse_forward(message)

        # Write .md file
        dest, rel = _media_dest(cfg, "text", created_at, str(message.message_id), "md")
        dest.write_text(content, encoding="utf-8")
        file_size = dest.stat().st_size

        db = await get_db()
        try:
            await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size, created_at, display_date, imported_at,
                    source, source_id, tags, is_forwarded, forward_from, forward_date,
                    transcribe_status)
                   VALUES (?, 'text', ?, ?, ?, ?, ?, 'telegram', ?, ?, ?, ?, ?, 'not_needed')""",
                (content, rel, file_size, created_at.isoformat(), display_date, now.isoformat(),
                 str(message.message_id), ",".join(tags),
                 is_forwarded, forward_from, forward_date),
            )
            await db.commit()
        finally:
            await db.close()

        await message.reply_text("Saved.", quote=True)

    application.add_handler(MessageHandler(
        allowed & filters.TEXT & ~filters.COMMAND, on_text
    ))

    # ── Photos ──────────────────────────────────────────────────────────

    async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message

        # Media group handling: collect and flush after timeout
        if message.media_group_id:
            group_id = message.media_group_id
            if group_id not in _media_groups:
                _media_groups[group_id] = []
            _media_groups[group_id].append(message)

            # Cancel existing timer and start new one
            old_timer = _media_group_timers.get(group_id)
            if old_timer:
                old_timer.cancel()

            loop = asyncio.get_event_loop()
            _media_group_timers[group_id] = loop.call_later(
                _MEDIA_GROUP_TIMEOUT,
                lambda gid=group_id: asyncio.ensure_future(_flush_media_group(gid, context)),
            )
            return

        # Single photo
        cfg = get_config()
        now = _now()
        created_at = _parse_created_at(message)
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)
        is_forwarded, forward_from, forward_date = _parse_forward(message)

        photo = message.photo[-1]  # highest resolution
        dest, rel = _media_dest(cfg, "image", created_at, str(message.message_id), "jpg")
        file_obj = await photo.get_file()
        await file_obj.download_to_drive(str(dest))

        file_size = dest.stat().st_size if dest.exists() else None

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size, created_at, display_date, imported_at,
                    source, source_id, tags, is_forwarded, forward_from, forward_date,
                    transcribe_status)
                   VALUES (?, 'image', ?, ?, ?, ?, ?, 'telegram', ?, ?, ?, ?, ?, 'not_needed')""",
                (content, rel, file_size, created_at.isoformat(), display_date, now.isoformat(),
                 str(message.message_id), ",".join(tags),
                 is_forwarded, forward_from, forward_date),
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

    application.add_handler(MessageHandler(
        allowed & filters.PHOTO, on_photo
    ))

    # ── Video / Video note ──────────────────────────────────────────────

    async def on_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        cfg = get_config()
        now = _now()
        created_at = _parse_created_at(message)
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        video = message.video or message.video_note
        ext = "mp4"
        duration = video.duration if video else None

        dest, rel = _media_dest(cfg, "video", created_at, str(message.message_id), ext)
        file_obj = await video.get_file()
        await file_obj.download_to_drive(str(dest))

        file_size = dest.stat().st_size if dest.exists() else None

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size, duration,
                    created_at, display_date, imported_at,
                    source, source_id, tags, transcribe_status)
                   VALUES (?, 'video', ?, ?, ?, ?, ?, ?, 'telegram', ?, ?, 'pending')""",
                (content, rel, file_size, duration,
                 created_at.isoformat(), display_date, now.isoformat(),
                 str(message.message_id), ",".join(tags)),
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

    application.add_handler(MessageHandler(
        allowed & (filters.VIDEO | filters.VIDEO_NOTE), on_video
    ))

    # ── Voice / Audio ───────────────────────────────────────────────────

    async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        cfg = get_config()
        now = _now()
        created_at = _parse_created_at(message)
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        audio = message.voice or message.audio
        ext = "ogg" if message.voice else (audio.file_name or "audio.mp3").split(".")[-1]
        duration = audio.duration if audio else None

        dest, rel = _media_dest(cfg, "audio", created_at, str(message.message_id), ext)
        file_obj = await audio.get_file()
        await file_obj.download_to_drive(str(dest))

        file_size = dest.stat().st_size if dest.exists() else None

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size, duration,
                    created_at, display_date, imported_at,
                    source, source_id, tags, transcribe_status)
                   VALUES (?, 'audio', ?, ?, ?, ?, ?, ?, 'telegram', ?, ?, 'pending')""",
                (content, rel, file_size, duration,
                 created_at.isoformat(), display_date, now.isoformat(),
                 str(message.message_id), ",".join(tags)),
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

    application.add_handler(MessageHandler(
        allowed & (filters.VOICE | filters.AUDIO), on_voice
    ))

    # ── Documents ───────────────────────────────────────────────────────

    async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
        message = update.message
        cfg = get_config()
        now = _now()
        created_at = _parse_created_at(message)
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        doc = message.document
        fname = doc.file_name or "file"
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "bin"

        # Classify by extension
        video_exts = {"mp4", "mov", "avi", "mkv", "webm"}
        audio_exts = {"mp3", "wav", "ogg", "m4a", "flac", "aac"}
        image_exts = {"jpg", "jpeg", "png", "gif", "webp", "heic"}

        if ext in video_exts:
            media_type = "video"
            transcribe_status = "pending"
        elif ext in audio_exts:
            media_type = "audio"
            transcribe_status = "pending"
        elif ext in image_exts:
            media_type = "image"
            transcribe_status = "not_needed"
        else:
            media_type = "text"
            transcribe_status = "not_needed"

        dest, rel = _media_dest(cfg, media_type, created_at, str(message.message_id), ext)
        file_obj = await doc.get_file()
        await file_obj.download_to_drive(str(dest))

        file_size = dest.stat().st_size if dest.exists() else None

        db = await get_db()
        try:
            cursor = await db.execute(
                """INSERT INTO notes
                   (content, media_type, file_path, file_size,
                    created_at, display_date, imported_at,
                    source, source_id, tags, transcribe_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'telegram', ?, ?, ?)""",
                (content, media_type, rel, file_size,
                 created_at.isoformat(), display_date, now.isoformat(),
                 str(message.message_id), ",".join(tags), transcribe_status),
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

    application.add_handler(MessageHandler(
        allowed & filters.Document.ALL, on_document
    ))

    return application


async def run_bot():
    """Start the Telegram bot with its transcription worker."""
    from braindump.transcribe.engine import TranscribeWorker

    cfg = get_config()
    cfg.ensure_dirs()
    await init_db()

    worker = TranscribeWorker()
    application = create_app(worker)

    worker_task = asyncio.create_task(worker.run())

    print("Starting Telegram bot...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    print("Bot is running. Press Ctrl+C to stop.")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        worker.stop()
        worker_task.cancel()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
