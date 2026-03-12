"""Test Telegram Bot connectivity using the Bot API directly (via requests).

Can be run as:
  - pytest: uv run python -m pytest tests/test_telegram_bot.py -v -s
  - standalone: uv run python tests/test_telegram_bot.py
"""

import json
import urllib.request
import urllib.error

BOT_TOKEN = "8294995266:AAFEqijTbvpOJ5vlkrApf3ahXDgerhdY0IY"
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
ALLOWED_USER = 5439573095


def _api_call(method: str, params: dict | None = None) -> dict:
    """Call a Telegram Bot API method."""
    url = f"{API_BASE}/{method}"
    if params:
        data = json.dumps(params).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}
        )
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def test_get_me():
    """Verify the bot token is valid by calling getMe."""
    result = _api_call("getMe")
    assert result["ok"], f"getMe failed: {result}"
    bot = result["result"]
    assert bot["is_bot"] is True
    assert "username" in bot
    print(f"Bot verified: @{bot['username']} (id={bot['id']})")


def test_get_updates():
    """Check for recent messages/updates."""
    result = _api_call("getUpdates", {"limit": 5, "timeout": 0})
    assert result["ok"], f"getUpdates failed: {result}"
    assert isinstance(result["result"], list)
    print(f"Recent updates: {len(result['result'])}")


def test_send_message_to_owner():
    """Send a test message to the bot owner."""
    result = _api_call(
        "sendMessage",
        {"chat_id": ALLOWED_USER, "text": "braindump bot test: connectivity OK"},
    )
    assert result["ok"], f"sendMessage failed: {result}"
    msg = result["result"]
    assert "message_id" in msg
    print(f"Message sent: message_id={msg['message_id']} to chat_id={ALLOWED_USER}")


def test_get_webhook_info():
    """Check webhook status (should be empty for polling mode)."""
    result = _api_call("getWebhookInfo")
    assert result["ok"], f"getWebhookInfo failed: {result}"
    info = result["result"]
    # For polling mode, URL should be empty
    assert info.get("url", "") == "", f"Unexpected webhook set: {info['url']}"
    print(f"Webhook: none (polling mode), pending: {info.get('pending_update_count', 0)}")


if __name__ == "__main__":
    print("=" * 60)
    print("Telegram Bot API Connectivity Test")
    print("=" * 60)

    for name, fn in [
        ("getMe", test_get_me),
        ("getWebhookInfo", test_get_webhook_info),
        ("getUpdates", test_get_updates),
        ("sendMessage", test_send_message_to_owner),
    ]:
        print(f"\n--- {name} ---")
        try:
            fn()
            print("  PASS")
        except Exception as e:
            print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    print("All connectivity tests completed.")
    print("=" * 60)
