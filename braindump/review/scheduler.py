"""ReviewScheduler — daily review of historical notes via Telegram."""

import asyncio
import logging
from datetime import datetime, time, timedelta

from braindump.config import Config, get_timezone
from braindump.database import get_db

logger = logging.getLogger("braindump.review")


class ReviewScheduler:
    """Async scheduler that sends daily note reviews at a configured time."""

    def __init__(self, cfg: Config, bot):
        self.cfg = cfg
        self.bot = bot
        self.last_review: str | None = None
        self._stopped = False

    def stop(self):
        self._stopped = True

    async def run(self):
        """Main loop: sleep until next scheduled time, then send review."""
        rc = self.cfg.review
        if not rc.enabled:
            logger.info("Daily review disabled")
            return

        chat_id = rc.chat_id or (
            self.cfg.telegram.allowed_users[0]
            if self.cfg.telegram.allowed_users
            else 0
        )
        if not chat_id:
            logger.warning("Review enabled but no chat_id configured — disabling")
            return

        tz = get_timezone()
        schedule_time = _parse_schedule(rc.schedule)
        logger.info(
            "Review scheduler started: %s daily, %d notes, chat_id=%d",
            rc.schedule,
            rc.count,
            chat_id,
        )

        # On startup: check if we missed today's review (handles restart)
        if await self._missed_today(tz, schedule_time):
            logger.info("Missed today's review — sending now")
            await self._send_review(chat_id)

        while not self._stopped:
            now = datetime.now(tz)
            next_run = _compute_next_run(now, schedule_time, tz)
            delta = (next_run - now).total_seconds()
            logger.info(
                "Next review in %.0f seconds (%s)",
                delta,
                next_run.isoformat(),
            )
            try:
                await asyncio.sleep(delta)
            except asyncio.CancelledError:
                logger.info("Review scheduler cancelled")
                return
            if self._stopped:
                return
            await self._send_review(chat_id)

    async def _missed_today(self, tz, schedule_time: time) -> bool:
        """Return True if today's scheduled time has passed but no review sent."""
        now = datetime.now(tz)
        today_scheduled = datetime.combine(now.date(), schedule_time, tzinfo=tz)
        if now < today_scheduled:
            return False
        return not await _has_sent_today(tz)

    async def _send_review(self, chat_id: int):
        """Select random notes and send the review message."""
        rc = self.cfg.review
        tz = get_timezone()

        notes = await _get_eligible_notes(
            count=rc.count,
            min_age_days=rc.min_age_days,
            min_content_length=rc.min_content_length,
        )

        if not notes:
            logger.info("No eligible notes for review — skipping")
            return

        text = _format_review(notes)

        try:
            await self.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error("Failed to send review: %s", e)
            return

        # Record sent notes
        sent_at = datetime.now(tz).isoformat()
        await _log_review([n["id"] for n in notes], sent_at)
        self.last_review = sent_at
        logger.info("Review sent: %d notes", len(notes))


# ── Helpers ──────────────────────────────────────────────────────


def _parse_schedule(schedule: str) -> time:
    """Parse 'HH:MM' string to a time object."""
    parts = schedule.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def _compute_next_run(now: datetime, schedule_time: time, tz) -> datetime:
    """Compute the next datetime to run the review."""
    today_run = datetime.combine(now.date(), schedule_time, tzinfo=tz)
    if now < today_run:
        return today_run
    # Already past today's time — schedule for tomorrow
    return datetime.combine(now.date() + timedelta(days=1), schedule_time, tzinfo=tz)


async def _has_sent_today(tz) -> bool:
    """Check if a review was already sent today (based on review_log)."""
    today = datetime.now(tz).strftime("%Y-%m-%d")
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT 1 FROM review_log WHERE date(sent_at) = ? LIMIT 1",
            (today,),
        )
        return await cursor.fetchone() is not None
    finally:
        await db.close()


async def _get_eligible_notes(
    count: int, min_age_days: int, min_content_length: int
) -> list[dict]:
    """Select random notes eligible for daily review."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """
            SELECT id, content, transcript, media_type,
                   created_at, ai_title, ai_summary
            FROM notes
            WHERE created_at < datetime('now', ? || ' days')
              AND is_deleted = 0
              AND (length(content) >= ? OR transcript IS NOT NULL)
              AND id NOT IN (
                SELECT note_id FROM review_log
                WHERE sent_at > datetime('now', '-30 days')
              )
            ORDER BY RANDOM()
            LIMIT ?
            """,
            (f"-{min_age_days}", min_content_length, count),
        )
        return [dict(row) for row in await cursor.fetchall()]
    finally:
        await db.close()


async def _log_review(note_ids: list[int], sent_at: str):
    """Record that notes were sent in a daily review."""
    db = await get_db()
    try:
        for nid in note_ids:
            await db.execute(
                "INSERT INTO review_log (note_id, sent_at) VALUES (?, ?)",
                (nid, sent_at),
            )
        await db.commit()
    finally:
        await db.close()


def _format_review(notes: list[dict]) -> str:
    """Format notes into the review message."""
    lines = ["\U0001f504 每日回顾\n"]

    for note in notes:
        date_str = note["created_at"][:10]
        lines.append(f"\U0001f4c5 {date_str}")

        if note["ai_title"]:
            lines.append(note["ai_title"])
            summary = note["ai_summary"] or ""
            if summary:
                lines.append(summary)
        else:
            # No AI summary — use raw content or transcript
            raw = note["content"] or note["transcript"] or ""
            preview = raw[:100].replace("\n", " ")
            if len(raw) > 100:
                preview += "..."
            if note["media_type"] == "image":
                preview = "\U0001f4f7 " + preview
            lines.append(preview)

        lines.append("")  # blank line between notes

    return "\n".join(lines).rstrip()
