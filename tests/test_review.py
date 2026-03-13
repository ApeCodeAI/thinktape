"""Tests for the daily review scheduler."""

import asyncio
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from braindump.config import Config, GeneralConfig, TelegramConfig, ReviewConfig
from braindump.review.scheduler import (
    ReviewScheduler,
    _compute_next_run,
    _format_review,
    _parse_schedule,
)

TZ = ZoneInfo("Asia/Shanghai")


# ── Unit tests for helpers ───────────────────────────────────────


def test_parse_schedule():
    assert _parse_schedule("09:00") == time(9, 0)
    assert _parse_schedule("23:30") == time(23, 30)
    assert _parse_schedule(" 08:15 ") == time(8, 15)


def test_compute_next_run_before_schedule():
    """If current time is before the schedule, next run is today."""
    now = datetime(2026, 3, 13, 7, 0, tzinfo=TZ)
    schedule = time(9, 0)
    result = _compute_next_run(now, schedule, TZ)
    assert result.date() == now.date()
    assert result.hour == 9
    assert result.minute == 0


def test_compute_next_run_after_schedule():
    """If current time is after the schedule, next run is tomorrow."""
    now = datetime(2026, 3, 13, 10, 0, tzinfo=TZ)
    schedule = time(9, 0)
    result = _compute_next_run(now, schedule, TZ)
    assert result.date() == now.date() + timedelta(days=1)
    assert result.hour == 9


def test_format_review_with_ai():
    notes = [
        {
            "id": 1,
            "content": "some content",
            "transcript": None,
            "media_type": "text",
            "created_at": "2026-01-15T10:00:00+08:00",
            "ai_title": "关于 Agent 落地的思考",
            "ai_summary": "讨论了当前 Agent 系统在实际业务中落地的三个关键瓶颈...",
        },
    ]
    text = _format_review(notes)
    assert "每日回顾" in text
    assert "2026-01-15" in text
    assert "关于 Agent 落地的思考" in text
    assert "三个关键瓶颈" in text


def test_format_review_without_ai():
    notes = [
        {
            "id": 2,
            "content": "这是一段没有AI摘要的笔记内容" * 10,
            "transcript": None,
            "media_type": "text",
            "created_at": "2025-12-03T15:00:00+08:00",
            "ai_title": None,
            "ai_summary": None,
        },
    ]
    text = _format_review(notes)
    assert "2025-12-03" in text
    assert "这是一段没有AI摘要的笔记内容" in text
    # Content should be truncated at 100 chars
    assert "..." in text


def test_format_review_image_note():
    notes = [
        {
            "id": 3,
            "content": "一张照片的描述",
            "transcript": None,
            "media_type": "image",
            "created_at": "2025-10-20T08:00:00+08:00",
            "ai_title": None,
            "ai_summary": None,
        },
    ]
    text = _format_review(notes)
    assert "\U0001f4f7" in text


def test_format_review_transcript_fallback():
    notes = [
        {
            "id": 4,
            "content": "",
            "transcript": "这是转写内容",
            "media_type": "audio",
            "created_at": "2025-11-01T09:00:00+08:00",
            "ai_title": None,
            "ai_summary": None,
        },
    ]
    text = _format_review(notes)
    assert "这是转写内容" in text


def test_format_review_empty():
    text = _format_review([])
    assert "每日回顾" in text


# ── ReviewScheduler tests ────────────────────────────────────────


def _make_cfg(enabled=True, count=3, schedule="09:00", chat_id=12345):
    cfg = Config()
    cfg.general = GeneralConfig(
        data_dir=Path("/tmp/test-braindump"),
        timezone="Asia/Shanghai",
    )
    cfg.telegram = TelegramConfig(allowed_users=[12345])
    cfg.review = ReviewConfig(
        enabled=enabled,
        count=count,
        schedule=schedule,
        min_age_days=7,
        min_content_length=20,
        chat_id=chat_id,
    )
    return cfg


def test_scheduler_init():
    cfg = _make_cfg()
    bot = MagicMock()
    scheduler = ReviewScheduler(cfg, bot)
    assert scheduler.last_review is None
    assert scheduler._stopped is False


async def test_scheduler_disabled():
    """Scheduler should return immediately when disabled."""
    cfg = _make_cfg(enabled=False)
    bot = MagicMock()
    scheduler = ReviewScheduler(cfg, bot)
    # run() should complete without error
    await scheduler.run()


async def test_scheduler_no_chat_id():
    """Scheduler should warn and return when no chat_id configured."""
    cfg = _make_cfg(chat_id=0)
    cfg.telegram.allowed_users = []
    bot = MagicMock()
    scheduler = ReviewScheduler(cfg, bot)
    await scheduler.run()


async def test_send_review_no_eligible_notes():
    """send_review should skip when no eligible notes exist."""
    cfg = _make_cfg()
    bot = MagicMock()
    bot.send_message = AsyncMock()
    scheduler = ReviewScheduler(cfg, bot)

    with patch(
        "braindump.review.scheduler._get_eligible_notes",
        new_callable=AsyncMock,
        return_value=[],
    ):
        await scheduler._send_review(12345)

    bot.send_message.assert_not_called()
    assert scheduler.last_review is None


async def test_send_review_success():
    """send_review should format and send notes, then log."""
    cfg = _make_cfg()
    bot = MagicMock()
    bot.send_message = AsyncMock()
    scheduler = ReviewScheduler(cfg, bot)

    fake_notes = [
        {
            "id": 10,
            "content": "test note",
            "transcript": None,
            "media_type": "text",
            "created_at": "2025-06-01T10:00:00+08:00",
            "ai_title": "测试标题",
            "ai_summary": "测试摘要",
        },
    ]

    with patch(
        "braindump.review.scheduler._get_eligible_notes",
        new_callable=AsyncMock,
        return_value=fake_notes,
    ), patch(
        "braindump.review.scheduler._log_review",
        new_callable=AsyncMock,
    ) as mock_log:
        await scheduler._send_review(12345)

    bot.send_message.assert_called_once()
    call_kwargs = bot.send_message.call_args
    assert call_kwargs.kwargs["chat_id"] == 12345
    assert "测试标题" in call_kwargs.kwargs["text"]

    mock_log.assert_called_once()
    assert mock_log.call_args[0][0] == [10]
    assert scheduler.last_review is not None


async def test_send_review_telegram_failure():
    """send_review should log error and NOT record when telegram fails."""
    cfg = _make_cfg()
    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=Exception("Telegram error"))
    scheduler = ReviewScheduler(cfg, bot)

    fake_notes = [
        {
            "id": 20,
            "content": "test",
            "transcript": None,
            "media_type": "text",
            "created_at": "2025-06-01T10:00:00+08:00",
            "ai_title": None,
            "ai_summary": None,
        },
    ]

    with patch(
        "braindump.review.scheduler._get_eligible_notes",
        new_callable=AsyncMock,
        return_value=fake_notes,
    ), patch(
        "braindump.review.scheduler._log_review",
        new_callable=AsyncMock,
    ) as mock_log:
        await scheduler._send_review(12345)

    # Should NOT log the review since send failed
    mock_log.assert_not_called()
    assert scheduler.last_review is None
