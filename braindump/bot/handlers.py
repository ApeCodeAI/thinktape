"""Telegram Bot message handlers using Pyrogram."""

import asyncio
import hashlib
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

from braindump.config import get_config
from braindump.database import get_db, init_db

TZ_CST = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(TZ_CST)


def _display_date(dt: datetime, boundary_hour: int) -> str:
    if dt.hour < boundary_hour:
        d = dt.date() - timedelta(days=1)
    else:
        d = dt.date()
    return d.isoformat()


def _media_dest(cfg, media_type: str, dt: datetime, source_id: str, ext: str) -> tuple[Path, str]:
    """Return (absolute_path, relative_path) for a media file."""
    ts = dt.strftime("%Y%m%d_%H%M%S")
    fname = f"{ts}_tg{source_id}.{ext}"
    year, month, day = dt.strftime("%Y"), dt.strftime("%m"), dt.strftime("%d")
    rel = f"media/{media_type}/{year}/{month}/{day}/{fname}"
    abs_path = cfg.data_dir / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    return abs_path, rel


def create_bot() -> Client:
    """Create and configure the Pyrogram bot client."""
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
    async def on_start(client: Client, message: Message):
        await message.reply_text(
            "**braindump** — dump your brain.\n\n"
            "Send me text, images, videos, or voice messages.\n"
            "Everything will be saved and searchable."
        )

    @bot.on_message(allowed_filter & filters.command("stats"))
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

    @bot.on_message(allowed_filter & filters.text & ~filters.command(["start", "stats", "recent", "status"]))
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
            forward_date = message.forward_date.replace(tzinfo=timezone.utc).astimezone(TZ_CST).isoformat()

        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(TZ_CST)
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)

        # Write .md file
        dest, rel = _media_dest(cfg, "text", created_at, str(message.id), "md")
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
                 str(message.id), ",".join(tags),
                 is_forwarded, forward_from, forward_date),
            )
            await db.commit()
        finally:
            await db.close()

        await message.reply_text("Saved.", quote=True)

    @bot.on_message(allowed_filter & filters.photo)
    async def on_photo(client: Client, message: Message):
        """Handle photo messages."""
        cfg = get_config()
        now = _now()
        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(TZ_CST)
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
                    source, source_id, tags, transcribe_status)
                   VALUES (?, 'image', ?, ?, ?, ?, ?, 'telegram', ?, ?, 'not_needed')""",
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
    async def on_video(client: Client, message: Message):
        """Handle video messages."""
        cfg = get_config()
        now = _now()
        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(TZ_CST)
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        video = message.video or message.video_note
        ext = "mp4"
        duration = video.duration if video else None

        dest, rel = _media_dest(cfg, "video", created_at, str(message.id), ext)
        await message.download(file_name=str(dest))

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

        await message.reply_text("Video saved. Transcription queued.", quote=True)

    @bot.on_message(allowed_filter & (filters.voice | filters.audio))
    async def on_voice(client: Client, message: Message):
        """Handle voice/audio messages."""
        cfg = get_config()
        now = _now()
        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(TZ_CST)
        display_date = _display_date(created_at, cfg.general.day_boundary_hour)
        content = message.caption or ""
        tags = _extract_tags(content)

        audio = message.voice or message.audio
        ext = "ogg" if message.voice else (audio.file_name or "audio.mp3").split(".")[-1]
        duration = audio.duration if audio else None

        dest, rel = _media_dest(cfg, "audio", created_at, str(message.id), ext)
        await message.download(file_name=str(dest))

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

        await message.reply_text("Voice saved. Transcription queued.", quote=True)

    @bot.on_message(allowed_filter & filters.document)
    async def on_document(client: Client, message: Message):
        """Handle document messages (try to detect media type)."""
        cfg = get_config()
        now = _now()
        created_at = (message.date or now).replace(tzinfo=timezone.utc).astimezone(TZ_CST)
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

        dest, rel = _media_dest(cfg, media_type, created_at, str(message.id), ext)
        await message.download(file_name=str(dest))

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
                 str(message.id), ",".join(tags), transcribe_status),
            )
            note_id = cursor.lastrowid
            await db.execute(
                "INSERT INTO attachments (note_id, file_path, media_type, file_size) VALUES (?, ?, ?, ?)",
                (note_id, rel, media_type, file_size),
            )
            await db.commit()
        finally:
            await db.close()

        await message.reply_text(f"File saved ({media_type}).", quote=True)

    return bot


def _extract_tags(text: str) -> list[str]:
    """Extract #hashtags from text."""
    import re
    return list(dict.fromkeys(
        re.findall(r"(?:^|\s)#([a-zA-Z\u4e00-\u9fff][\w/\u4e00-\u9fff]*)", text)
    ))


async def run_bot():
    """Start the Telegram bot."""
    cfg = get_config()
    cfg.ensure_dirs()
    await init_db()
    bot = create_bot()
    print(f"Starting Telegram bot...")
    await bot.start()
    print("Bot is running. Press Ctrl+C to stop.")
    try:
        await asyncio.Event().wait()  # Run forever
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await bot.stop()
