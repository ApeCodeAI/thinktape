"""Tests for large video download optimization (Phase 3).

Tests cover: disk space check, size formatting, progress callback, download timeout.
"""

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from braindump.bot.handlers import (
    DOWNLOAD_TIMEOUT,
    _check_disk_space,
    _download_with_timeout,
    _format_size,
    _make_progress_callback,
)


# --- _format_size ---

class TestFormatSize:
    def test_bytes(self):
        assert _format_size(500) == "500B"

    def test_kilobytes(self):
        assert _format_size(1024) == "1KB"
        assert _format_size(2048) == "2KB"

    def test_megabytes(self):
        assert _format_size(1024 * 1024) == "1MB"
        assert _format_size(500 * 1024 * 1024) == "500MB"

    def test_gigabytes(self):
        assert _format_size(1024 * 1024 * 1024) == "1.0GB"
        assert _format_size(int(1.5 * 1024**3)) == "1.5GB"

    def test_zero(self):
        assert _format_size(0) == "0B"


# --- _check_disk_space ---

class TestCheckDiskSpace:
    def _make_cfg(self, data_dir="/tmp/test"):
        return SimpleNamespace(data_dir=Path(data_dir))

    def test_none_file_size_skips_check(self):
        cfg = self._make_cfg()
        assert _check_disk_space(cfg, None) is None

    def test_zero_file_size_skips_check(self):
        cfg = self._make_cfg()
        assert _check_disk_space(cfg, 0) is None

    def test_negative_file_size_skips_check(self):
        cfg = self._make_cfg()
        assert _check_disk_space(cfg, -1) is None

    @patch("braindump.bot.handlers.shutil.disk_usage")
    def test_enough_space(self, mock_usage):
        mock_usage.return_value = SimpleNamespace(free=1000)
        cfg = self._make_cfg()
        # file_size=100, required=150, free=1000 → OK
        assert _check_disk_space(cfg, 100) is None

    @patch("braindump.bot.handlers.shutil.disk_usage")
    def test_insufficient_space(self, mock_usage):
        mock_usage.return_value = SimpleNamespace(free=100)
        cfg = self._make_cfg()
        # file_size=100, required=150, free=100 → error
        result = _check_disk_space(cfg, 100)
        assert result is not None
        assert "磁盘空间不足" in result

    @patch("braindump.bot.handlers.shutil.disk_usage")
    def test_exact_boundary(self, mock_usage):
        # free == required → should pass (not strictly less than)
        mock_usage.return_value = SimpleNamespace(free=150)
        cfg = self._make_cfg()
        assert _check_disk_space(cfg, 100) is None

    @patch("braindump.bot.handlers.shutil.disk_usage")
    def test_just_below_boundary(self, mock_usage):
        mock_usage.return_value = SimpleNamespace(free=149)
        cfg = self._make_cfg()
        result = _check_disk_space(cfg, 100)
        assert result is not None

    @patch("braindump.bot.handlers.shutil.disk_usage", side_effect=OSError("disk error"))
    def test_os_error_is_graceful(self, mock_usage):
        cfg = self._make_cfg()
        # Should not raise, just return None
        assert _check_disk_space(cfg, 100) is None


# --- _make_progress_callback ---

class TestProgressCallback:
    @pytest.mark.asyncio
    async def test_no_update_at_zero_percent(self):
        message = MagicMock()
        message.reply_text = AsyncMock()
        progress_cb, state = _make_progress_callback(message)
        await progress_cb(0, 1000)
        message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_update_below_20_percent(self):
        message = MagicMock()
        message.reply_text = AsyncMock()
        progress_cb, state = _make_progress_callback(message)
        await progress_cb(100, 1000)  # 10%
        message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_at_20_percent(self):
        message = MagicMock()
        message.reply_text = AsyncMock(return_value=MagicMock())
        progress_cb, state = _make_progress_callback(message)
        await progress_cb(200, 1000)  # 20%
        message.reply_text.assert_called_once()
        call_text = message.reply_text.call_args[0][0]
        assert "20%" in call_text
        assert "下载中" in call_text

    @pytest.mark.asyncio
    async def test_edit_on_subsequent_update(self):
        message = MagicMock()
        status_msg = MagicMock()
        status_msg.edit_text = AsyncMock()
        message.reply_text = AsyncMock(return_value=status_msg)
        progress_cb, state = _make_progress_callback(message)

        # First update at 20%
        await progress_cb(200, 1000)
        assert state["status_msg"] is status_msg

        # Force time to pass rate limit
        state["last_update_time"] = time.monotonic() - 4.0

        # Second update at 40%
        await progress_cb(400, 1000)
        status_msg.edit_text.assert_called_once()
        call_text = status_msg.edit_text.call_args[0][0]
        assert "40%" in call_text

    @pytest.mark.asyncio
    async def test_rate_limit_prevents_rapid_updates(self):
        message = MagicMock()
        message.reply_text = AsyncMock(return_value=MagicMock())
        progress_cb, state = _make_progress_callback(message)

        # First update at 20%
        await progress_cb(200, 1000)
        assert message.reply_text.call_count == 1

        # Immediately try 40% — should be rate-limited
        await progress_cb(400, 1000)
        # Still only 1 call (reply_text), no edit_text
        assert message.reply_text.call_count == 1

    @pytest.mark.asyncio
    async def test_zero_total_is_noop(self):
        message = MagicMock()
        message.reply_text = AsyncMock()
        progress_cb, state = _make_progress_callback(message)
        await progress_cb(100, 0)
        message.reply_text.assert_not_called()


# --- _download_with_timeout ---

class TestDownloadWithTimeout:
    @pytest.mark.asyncio
    async def test_successful_download(self, tmp_path):
        dest = tmp_path / "video.mp4"
        message = MagicMock()
        message.download = AsyncMock()
        await _download_with_timeout(message, dest, progress_cb=None)
        message.download.assert_called_once_with(file_name=str(dest), progress=None)

    @pytest.mark.asyncio
    async def test_timeout_cleans_up_partial_file(self, tmp_path):
        dest = tmp_path / "video.mp4"
        dest.write_text("partial data")  # simulate partial download

        async def slow_download(**kwargs):
            await asyncio.sleep(10)

        message = MagicMock()
        message.download = AsyncMock(side_effect=slow_download)

        with patch("braindump.bot.handlers.DOWNLOAD_TIMEOUT", 0.01):
            with pytest.raises(asyncio.TimeoutError):
                await _download_with_timeout(message, dest, progress_cb=None)

        # Partial file should be cleaned up
        assert not dest.exists()

    @pytest.mark.asyncio
    async def test_timeout_no_file_no_error(self, tmp_path):
        dest = tmp_path / "video.mp4"
        # File doesn't exist — should not raise on cleanup

        async def slow_download(**kwargs):
            await asyncio.sleep(10)

        message = MagicMock()
        message.download = AsyncMock(side_effect=slow_download)

        with patch("braindump.bot.handlers.DOWNLOAD_TIMEOUT", 0.01):
            with pytest.raises(asyncio.TimeoutError):
                await _download_with_timeout(message, dest, progress_cb=None)


# --- DOWNLOAD_TIMEOUT constant ---

class TestConstants:
    def test_timeout_is_30_minutes(self):
        assert DOWNLOAD_TIMEOUT == 1800
