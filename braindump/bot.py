"""Telegram Bot (Pyrofork)."""
from __future__ import annotations

import logging
import re
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.types import Message

from .config import Config
from .core import BrainDump
from .transcribe import TranscribeQueue

log = logging.getLogger(__name__)

URL_RE = re.compile(
    r"https?://[^\s<>\"']+",
    re.IGNORECASE,
)

_TZ_CST = timezone(timedelta(hours=8))


def _extract_url(text: str) -> str | None:
    if not text:
        return None
    m = URL_RE.search(text)
    return m.group(0) if m else None


def _format_item_summary(item) -> str:
    when = item.created_at.astimezone(_TZ_CST).strftime("%m-%d %H:%M")
    tags = " ".join(f"#{t}" for t in item.tags) if item.tags else ""
    icon = {"thought": "💭", "bookmark": "🔖", "note": "📝"}.get(item.type, "📝")
    if item.has_audio:
        icon = "🎤"
    elif item.has_video:
        icon = "🎬"
    elif item.has_images:
        icon = "🖼️"
    body = (item.content or "").strip()
    if len(body) > 80:
        body = body[:77] + "…"
    parts = [f"{icon} {when}"]
    if body:
        parts.append(body)
    if tags:
        parts.append(tags)
    return "  ".join(parts)


class BrainDumpBot:
    """Pyrofork bot wrapping BrainDump."""

    def __init__(self, config: Config, brain: BrainDump, transcribe_queue: TranscribeQueue | None = None):
        if config.telegram is None:
            raise RuntimeError("telegram config missing")
        self.config = config
        self.brain = brain
        self.transcribe_queue = transcribe_queue
        self.allowed = set(config.telegram.allowed_users)

        self.client = Client(
            name=str(config.bot_session_path),
            api_id=config.telegram.api_id,
            api_hash=config.telegram.api_hash,
            bot_token=config.telegram.bot_token,
            workdir=str(config.data_dir),
            in_memory=False,
        )
        self._register_handlers()

    # ---------- lifecycle ----------

    async def start(self) -> None:
        await self.client.start()
        log.info("bot started")

    async def stop(self) -> None:
        try:
            await self.client.stop()
        except Exception:
            log.exception("bot stop error")

    # ---------- handlers ----------

    def _allowed(self, msg: Message) -> bool:
        user = msg.from_user
        return user is not None and user.id in self.allowed

    def _register_handlers(self) -> None:
        c = self.client

        @c.on_message(filters.command("start") & filters.private)
        async def _start(_, message: Message):
            if not self._allowed(message):
                return
            await message.reply_text(
                "👋 欢迎使用 braindump v2\n\n"
                "随手发送文字、语音、图片、链接，我会自动保存并整理。\n\n"
                "命令：\n"
                "/status — 统计信息\n"
                "/recent — 最近 5 条\n"
                "/search <关键词> — 搜索"
            )

        @c.on_message(filters.command("status") & filters.private)
        async def _status(_, message: Message):
            if not self._allowed(message):
                return
            stats = await self.brain.stats()
            lines = [
                f"📊 braindump 统计",
                f"总数: {stats.total}",
                f"今日: {stats.today}",
            ]
            if stats.by_type:
                lines.append("类型: " + " | ".join(f"{k} {v}" for k, v in stats.by_type.items()))
            await message.reply_text("\n".join(lines))

        @c.on_message(filters.command("recent") & filters.private)
        async def _recent(_, message: Message):
            if not self._allowed(message):
                return
            items = await self.brain.list(limit=5)
            if not items:
                await message.reply_text("还没有任何记录")
                return
            text = "\n\n".join(_format_item_summary(i) for i in items)
            await message.reply_text("📚 最近 5 条:\n\n" + text)

        @c.on_message(filters.command("search") & filters.private)
        async def _search(_, message: Message):
            if not self._allowed(message):
                return
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.reply_text("用法: /search <关键词>")
                return
            q = parts[1]
            items = await self.brain.search(q, limit=10)
            if not items:
                await message.reply_text(f"没有匹配 “{q}” 的记录")
                return
            text = "\n\n".join(_format_item_summary(i) for i in items)
            await message.reply_text(f"🔍 “{q}” 命中 {len(items)} 条:\n\n" + text)

        @c.on_message(filters.voice & filters.private)
        async def _voice(_, message: Message):
            if not self._allowed(message):
                return
            await self._handle_voice(message)

        @c.on_message(filters.video & filters.private)
        async def _video(_, message: Message):
            if not self._allowed(message):
                return
            await self._handle_video(message)

        @c.on_message(filters.video_note & filters.private)
        async def _video_note(_, message: Message):
            if not self._allowed(message):
                return
            await self._handle_video(message)

        @c.on_message(filters.photo & filters.private)
        async def _photo(_, message: Message):
            if not self._allowed(message):
                return
            await self._handle_photo(message)

        @c.on_message(filters.document & filters.private)
        async def _document(_, message: Message):
            if not self._allowed(message):
                return
            await self._handle_document(message)

        @c.on_message(filters.text & filters.private & ~filters.command(["start", "status", "recent", "search"]))
        async def _text(_, message: Message):
            if not self._allowed(message):
                return
            await self._handle_text(message)

    # ---------- per-type handlers ----------

    async def _handle_text(self, message: Message) -> None:
        text = (message.text or message.caption or "").strip()
        if not text:
            return
        url = _extract_url(text)
        item_type = "bookmark" if url else "thought"
        item = await self.brain.add(
            content=text,
            type=item_type,
            source="telegram",
            bookmark_url=url,
            telegram_message_id=message.id,
        )
        await message.reply_text(f"✅ 已保存 ({item.id[:15]}…)")

    async def _handle_photo(self, message: Message) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = await message.download(file_name=str(tmp_path / "photo.jpg"))
            if not file_path:
                await message.reply_text("⚠️ 图片下载失败")
                return
            caption = (message.caption or "").strip()
            item = await self.brain.add(
                content=caption,
                type="thought",
                source="telegram",
                image_paths=[Path(file_path)],
                telegram_message_id=message.id,
            )
            await message.reply_text(f"📷 已保存 ({item.id[:15]}…)")

    async def _handle_voice(self, message: Message) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = await message.download(file_name=str(tmp_path / "voice.ogg"))
            if not file_path:
                await message.reply_text("⚠️ 语音下载失败")
                return
            item = await self.brain.add(
                content="[转写中…]",
                type="thought",
                source="telegram",
                audio_path=Path(file_path),
                telegram_message_id=message.id,
            )
            if self.transcribe_queue is not None:
                self.transcribe_queue.enqueue(item.id)
            await message.reply_text(f"🎤 已保存，转写中… ({item.id[:15]}…)")

    async def _handle_video(self, message: Message) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = await message.download(file_name=str(tmp_path / "video.mp4"))
            if not file_path:
                await message.reply_text("⚠️ 视频下载失败")
                return
            caption = (message.caption or "").strip() or "[转写中…]"
            item = await self.brain.add(
                content=caption,
                type="thought",
                source="telegram",
                video_path=Path(file_path),
                telegram_message_id=message.id,
            )
            if self.transcribe_queue is not None:
                self.transcribe_queue.enqueue(item.id)
            await message.reply_text(f"🎬 已保存，转写中… ({item.id[:15]}…)")

    async def _handle_document(self, message: Message) -> None:
        doc = message.document
        if doc is None:
            return
        mime = (doc.mime_type or "").lower()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            file_path = await message.download(file_name=str(tmp_path / (doc.file_name or "file.bin")))
            if not file_path:
                await message.reply_text("⚠️ 文件下载失败")
                return
            src = Path(file_path)
            caption = (message.caption or "").strip()

            if mime.startswith("image/"):
                item = await self.brain.add(
                    content=caption,
                    type="thought",
                    source="telegram",
                    image_paths=[src],
                    telegram_message_id=message.id,
                )
            elif mime.startswith("audio/"):
                item = await self.brain.add(
                    content=caption or "[转写中…]",
                    type="thought",
                    source="telegram",
                    audio_path=src,
                    telegram_message_id=message.id,
                )
                if self.transcribe_queue is not None:
                    self.transcribe_queue.enqueue(item.id)
            elif mime.startswith("video/"):
                item = await self.brain.add(
                    content=caption or "[转写中…]",
                    type="thought",
                    source="telegram",
                    video_path=src,
                    telegram_message_id=message.id,
                )
                if self.transcribe_queue is not None:
                    self.transcribe_queue.enqueue(item.id)
            else:
                # Generic file — save caption as content, log filename.
                content = caption + (f"\n\n[文件: {doc.file_name}]" if doc.file_name else "")
                item = await self.brain.add(
                    content=content.strip(),
                    type="note",
                    source="telegram",
                    telegram_message_id=message.id,
                )
            await message.reply_text(f"📎 已保存 ({item.id[:15]}…)")
