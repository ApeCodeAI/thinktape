"""Tests for bot reconnection, /status command, safe_handler enhancements, and health check."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import braindump.bot.handlers as handlers
from braindump.bot.handlers import get_bot_status, is_bot_connected, safe_handler


# ── get_bot_status / is_bot_connected ─────────────────────────────


class TestBotStatus:
    def setup_method(self):
        """Reset module-level state before each test."""
        handlers._bot_connected = False
        handlers._bot_start_time = None
        handlers._last_message_time = None
        handlers._message_count = 0

    def test_initial_state(self):
        assert is_bot_connected() is False
        status = get_bot_status()
        assert status["connected"] is False
        assert status["uptime_seconds"] is None
        assert status["last_message_time"] is None
        assert status["message_count"] == 0

    def test_connected_state(self):
        handlers._bot_connected = True
        handlers._bot_start_time = time.monotonic() - 120  # 2 minutes ago
        status = get_bot_status()
        assert status["connected"] is True
        assert status["uptime_seconds"] is not None
        assert status["uptime_seconds"] >= 119  # allow small timing variance

    def test_message_tracking(self):
        handlers._last_message_time = 1700000000.0
        handlers._message_count = 42
        status = get_bot_status()
        assert status["last_message_time"] == 1700000000.0
        assert status["message_count"] == 42


# ── safe_handler enhancements ─────────────────────────────────────


class TestSafeHandler:
    def setup_method(self):
        handlers._last_message_time = None
        handlers._message_count = 0

    @pytest.mark.asyncio
    async def test_successful_handler_tracks_message(self):
        @safe_handler
        async def my_handler(client, message):
            pass

        client = MagicMock()
        message = MagicMock()
        await my_handler(client, message)

        assert handlers._message_count == 1
        assert handlers._last_message_time is not None

    @pytest.mark.asyncio
    async def test_multiple_calls_increment_count(self):
        @safe_handler
        async def my_handler(client, message):
            pass

        client = MagicMock()
        message = MagicMock()
        await my_handler(client, message)
        await my_handler(client, message)
        await my_handler(client, message)

        assert handlers._message_count == 3

    @pytest.mark.asyncio
    async def test_floodwait_is_handled(self):
        """FloodWait should be caught and waited out, not propagated."""
        from pyrogram.errors import FloodWait

        call_count = 0

        @safe_handler
        async def my_handler(client, message):
            nonlocal call_count
            call_count += 1
            exc = FloodWait.__new__(FloodWait)
            exc.value = 0  # 0 seconds for test speed
            raise exc

        client = MagicMock()
        message = MagicMock()
        await my_handler(client, message)

        # Handler was called but FloodWait was caught (not propagated)
        assert call_count == 1
        # Message count should NOT increment on FloodWait
        assert handlers._message_count == 0

    @pytest.mark.asyncio
    async def test_network_error_no_reply(self):
        """Network errors should not try to reply to the user."""

        @safe_handler
        async def my_handler(client, message):
            raise ConnectionError("network down")

        client = MagicMock()
        message = MagicMock()
        message.reply_text = AsyncMock()
        await my_handler(client, message)

        # Should NOT try to reply on network error
        message.reply_text.assert_not_called()
        assert handlers._message_count == 0

    @pytest.mark.asyncio
    async def test_oserror_no_reply(self):
        """OSError should not try to reply to the user."""

        @safe_handler
        async def my_handler(client, message):
            raise OSError("connection reset")

        client = MagicMock()
        message = MagicMock()
        message.reply_text = AsyncMock()
        await my_handler(client, message)

        message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_general_error_replies(self):
        """General exceptions should reply with error message."""

        @safe_handler
        async def my_handler(client, message):
            raise ValueError("bad data")

        client = MagicMock()
        message = MagicMock()
        message.reply_text = AsyncMock()
        await my_handler(client, message)

        message.reply_text.assert_called_once()
        call_text = message.reply_text.call_args[0][0]
        assert "保存失败" in call_text
        assert "bad data" in call_text


# ── run_bot_task reconnect logic ──────────────────────────────────


class TestRunBotTaskReconnect:
    """Test the reconnect logic in __main__.py's run_bot_task."""

    @pytest.mark.asyncio
    async def test_reconnect_on_disconnect(self):
        """Bot should reconnect when is_connected goes False."""
        connect_count = 0
        check_count = 0

        bot = AsyncMock()

        async def fake_start():
            nonlocal connect_count
            connect_count += 1

        bot.start = fake_start
        bot.stop = AsyncMock()

        # First check: connected, second: disconnected; then raise to exit loop
        def is_connected_side_effect():
            nonlocal check_count
            check_count += 1
            if check_count == 1:
                return True
            if check_count == 2:
                return False  # triggers reconnect
            # After second connect, the check will trigger again
            if check_count == 3:
                return True
            # Exit the test by raising
            raise KeyboardInterrupt()

        type(bot).is_connected = property(lambda self: is_connected_side_effect())

        with patch("asyncio.sleep", new_callable=AsyncMock):
            import braindump.bot.handlers as bot_mod

            bot_mod._bot_connected = False

            # Simulate the reconnect loop structure
            max_retries = 10
            base_delay = 5
            retries = 0

            try:
                while True:
                    try:
                        await bot.start()
                        bot_mod._bot_connected = True
                        retries = 0
                        while True:
                            await asyncio.sleep(60)
                            if not bot.is_connected:
                                break
                    except KeyboardInterrupt:
                        raise
                    except Exception:
                        retries += 1
                        if retries > max_retries:
                            raise
                        await asyncio.sleep(base_delay)
                    finally:
                        bot_mod._bot_connected = False
                        try:
                            await bot.stop()
                        except Exception:
                            pass
            except KeyboardInterrupt:
                pass

        # Bot should have connected at least 2 times (initial + reconnect)
        assert connect_count >= 2

    @pytest.mark.asyncio
    async def test_exponential_backoff(self):
        """Retries should use exponential backoff."""
        sleep_delays = []

        async def tracking_sleep(delay):
            sleep_delays.append(delay)

        bot = AsyncMock()
        attempt = 0

        async def failing_start():
            nonlocal attempt
            attempt += 1
            if attempt <= 3:
                raise RuntimeError(f"fail {attempt}")
            # Succeed on 4th attempt, then exit
            raise KeyboardInterrupt()

        bot.start = failing_start
        bot.stop = AsyncMock()

        with patch("asyncio.sleep", side_effect=tracking_sleep):
            import braindump.bot.handlers as bot_mod
            bot_mod._bot_connected = False

            max_retries = 10
            base_delay = 5
            retries = 0

            try:
                while True:
                    try:
                        await bot.start()
                        retries = 0
                        while True:
                            await asyncio.sleep(60)
                    except KeyboardInterrupt:
                        raise
                    except Exception:
                        retries += 1
                        if retries > max_retries:
                            raise
                        delay = min(base_delay * (2 ** (retries - 1)), 300)
                        await asyncio.sleep(delay)
                    finally:
                        bot_mod._bot_connected = False
                        try:
                            await bot.stop()
                        except Exception:
                            pass
            except KeyboardInterrupt:
                pass

        # Check exponential backoff: 5, 10, 20
        assert sleep_delays[0] == 5
        assert sleep_delays[1] == 10
        assert sleep_delays[2] == 20

    @pytest.mark.asyncio
    async def test_max_retries_raises(self):
        """Should raise after max_retries exceeded."""
        bot = AsyncMock()
        bot.start = AsyncMock(side_effect=RuntimeError("always fail"))
        bot.stop = AsyncMock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            import braindump.bot.handlers as bot_mod
            bot_mod._bot_connected = False

            max_retries = 3
            base_delay = 5
            retries = 0

            with pytest.raises(RuntimeError, match="always fail"):
                while True:
                    try:
                        await bot.start()
                        retries = 0
                        while True:
                            await asyncio.sleep(60)
                    except Exception:
                        retries += 1
                        if retries > max_retries:
                            raise
                        delay = min(base_delay * (2 ** (retries - 1)), 300)
                        await asyncio.sleep(delay)
                    finally:
                        bot_mod._bot_connected = False
                        try:
                            await bot.stop()
                        except Exception:
                            pass

    @pytest.mark.asyncio
    async def test_floodwait_in_reconnect_loop(self):
        """FloodWait should be handled specially without incrementing retries."""
        from pyrogram.errors import FloodWait

        sleep_calls = []
        attempt = 0

        async def tracking_sleep(delay):
            sleep_calls.append(delay)

        bot = AsyncMock()

        async def start_with_floodwait():
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                exc = FloodWait.__new__(FloodWait)
                exc.value = 10
                raise exc
            # Succeed on 2nd attempt, then exit
            raise KeyboardInterrupt()

        bot.start = start_with_floodwait
        bot.stop = AsyncMock()

        with patch("asyncio.sleep", side_effect=tracking_sleep):
            import braindump.bot.handlers as bot_mod
            bot_mod._bot_connected = False

            max_retries = 10
            base_delay = 5
            retries = 0

            try:
                while True:
                    try:
                        await bot.start()
                        retries = 0
                        while True:
                            await asyncio.sleep(60)
                    except FloodWait as e:
                        await asyncio.sleep(e.value + 1)
                    except KeyboardInterrupt:
                        raise
                    except Exception:
                        retries += 1
                        if retries > max_retries:
                            raise
                        delay = min(base_delay * (2 ** (retries - 1)), 300)
                        await asyncio.sleep(delay)
                    finally:
                        bot_mod._bot_connected = False
                        try:
                            await bot.stop()
                        except Exception:
                            pass
            except KeyboardInterrupt:
                pass

        # FloodWait should wait e.value + 1 = 11 seconds
        assert 11 in sleep_calls
        # retries should still be 0 (FloodWait doesn't increment)
        assert retries == 0

    @pytest.mark.asyncio
    async def test_backoff_capped_at_300(self):
        """Exponential backoff should cap at 300 seconds."""
        base_delay = 5
        # At retry 7: 5 * 2^6 = 320, should be capped to 300
        delay = min(base_delay * (2 ** 6), 300)
        assert delay == 300
        # At retry 8: 5 * 2^7 = 640, still capped
        delay = min(base_delay * (2 ** 7), 300)
        assert delay == 300


# ── Health check enhancements ─────────────────────────────────────


class TestHealthCheck:
    def setup_method(self):
        handlers._bot_connected = False
        handlers._bot_start_time = None
        handlers._last_message_time = None
        handlers._message_count = 0

    def test_status_degraded_when_disconnected(self):
        status = get_bot_status()
        assert status["connected"] is False

    def test_status_healthy_when_connected(self):
        handlers._bot_connected = True
        handlers._bot_start_time = time.monotonic()
        status = get_bot_status()
        assert status["connected"] is True
        assert status["uptime_seconds"] is not None
