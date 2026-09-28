"""Device-key auth — opt-in, backward compatible.

Model: the local machine (loopback) is always trusted. Remote clients
(phone over LAN, etc.) need a paired device key ONLY once at least one
device has been paired. With no devices paired, everything is allowed —
so existing single-machine setups keep working unchanged.

Keys live in <data_dir>/device_keys.json (read live, so `thinktape pair`
takes effect without restarting the daemon).
"""
from __future__ import annotations

import json
import os
import secrets
import tempfile
import time
from pathlib import Path

DEVICE_KEYS_FILE = "device_keys.json"
KEY_HEADER = "X-ThinkTape-Key"

_LOOPBACK = {"127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1"}


def is_loopback(host: str | None) -> bool:
    return (host or "") in _LOOPBACK


class DeviceKeyStore:
    """JSON-backed list of paired devices. Read fresh on each check."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / DEVICE_KEYS_FILE

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8")) or []
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, devices: list[dict]) -> None:
        # NamedTemporaryFile uses private permissions; replace atomically so
        # a crash cannot leave a partial or world-readable credentials file.
        tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.path.parent,
            prefix=".device_keys-", delete=False,
        )
        try:
            with tmp:
                json.dump(devices, tmp, ensure_ascii=False, indent=2)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.chmod(tmp.name, 0o600)
            os.replace(tmp.name, self.path)
        finally:
            Path(tmp.name).unlink(missing_ok=True)

    def keys(self) -> set[str]:
        return {d["key"] for d in self._load() if d.get("key")}

    def is_empty(self) -> bool:
        return not self.keys()

    def verify(self, provided: str | None) -> bool:
        if not provided:
            return False
        for k in self.keys():
            if secrets.compare_digest(k, provided):
                return True
        return False

    def add(self, name: str) -> dict:
        devices = self._load()
        entry = {
            "key": secrets.token_urlsafe(24),
            "name": name or "device",
            "created_at": int(time.time()),
        }
        devices.append(entry)
        self._save(devices)
        return entry

    def remove(self, name_or_prefix: str) -> int:
        devices = self._load()
        kept = [
            d
            for d in devices
            if d.get("name") != name_or_prefix
            and not d.get("key", "").startswith(name_or_prefix)
        ]
        removed = len(devices) - len(kept)
        if removed:
            self._save(kept)
        return removed

    def list_public(self) -> list[dict]:
        """Devices without exposing the full key."""
        out = []
        for d in self._load():
            key = d.get("key", "")
            out.append(
                {
                    "name": d.get("name"),
                    "created_at": d.get("created_at"),
                    "key_preview": (key[:6] + "…") if key else "",
                }
            )
        return out
