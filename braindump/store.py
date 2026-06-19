"""ItemStore — file-based storage. Each item is a directory."""
from __future__ import annotations

import asyncio
import re
import secrets
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterator

import yaml

from .models import Item

# Asia/Shanghai is fixed offset +08:00.
_TZ_CST = timezone(timedelta(hours=8))

_ID_RE = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")


def _now() -> datetime:
    return datetime.now(_TZ_CST)


def _generate_id(now: datetime | None = None) -> str:
    now = now or _now()
    rand = secrets.token_hex(2)
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{rand}"


def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=_TZ_CST)
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise ValueError(f"cannot parse datetime: {value!r}")


class ItemStore:
    """File-based storage. items_dir/<id>/{item.yaml, content.md, ...}."""

    def __init__(self, items_dir: Path):
        self.items_dir = Path(items_dir)
        self.items_dir.mkdir(parents=True, exist_ok=True)

    # ---------- path helpers ----------

    def item_dir(self, item_id: str) -> Path:
        return self.items_dir / item_id

    def yaml_path(self, item_id: str) -> Path:
        return self.item_dir(item_id) / "item.yaml"

    def content_path(self, item_id: str) -> Path:
        return self.item_dir(item_id) / "content.md"

    def audio_path(self, item_id: str) -> Path:
        # Default container; consumers should glob for audio.* if extension may vary.
        return self.item_dir(item_id) / "audio.opus"

    def video_path(self, item_id: str) -> Path:
        return self.item_dir(item_id) / "video.mp4"

    def images_dir(self, item_id: str) -> Path:
        return self.item_dir(item_id) / "images"

    def audio_file(self, item_id: str) -> Path | None:
        d = self.item_dir(item_id)
        for ext in ("opus", "ogg", "mp3", "m4a", "wav"):
            p = d / f"audio.{ext}"
            if p.exists():
                return p
        return None

    def video_file(self, item_id: str) -> Path | None:
        d = self.item_dir(item_id)
        for ext in ("mp4", "mov", "webm", "mkv"):
            p = d / f"video.{ext}"
            if p.exists():
                return p
        return None

    def image_files(self, item_id: str) -> list[Path]:
        d = self.images_dir(item_id)
        if not d.exists():
            return []
        return sorted(p for p in d.iterdir() if p.is_file() and not p.name.startswith("."))

    # ---------- CRUD ----------

    async def create(
        self,
        *,
        content: str,
        type: str = "thought",
        source: str = "telegram",
        audio_path: Path | None = None,
        image_paths: list[Path] | None = None,
        video_path: Path | None = None,
        bookmark_url: str | None = None,
        tags: list[str] | None = None,
        telegram_message_id: int | None = None,
        item_id: str | None = None,
    ) -> Item:
        return await asyncio.to_thread(
            self._create_sync,
            content=content,
            type=type,
            source=source,
            audio_path=audio_path,
            image_paths=image_paths,
            video_path=video_path,
            bookmark_url=bookmark_url,
            tags=tags,
            telegram_message_id=telegram_message_id,
            item_id=item_id,
        )

    def _create_sync(self, **kwargs) -> Item:
        now = _now()
        item_id = kwargs.pop("item_id", None) or _generate_id(now)
        # If collision, regenerate.
        while self.item_dir(item_id).exists():
            item_id = _generate_id(now)

        item_dir = self.item_dir(item_id)
        item_dir.mkdir(parents=True)

        audio_path = kwargs.pop("audio_path", None)
        image_paths = kwargs.pop("image_paths", None) or []
        video_path = kwargs.pop("video_path", None)

        has_audio = False
        has_images = False
        has_video = False

        # Copy media into the item directory.
        if audio_path:
            src = Path(audio_path)
            ext = src.suffix.lstrip(".") or "opus"
            dst = item_dir / f"audio.{ext}"
            shutil.copy2(src, dst)
            has_audio = True

        if image_paths:
            images_dir = self.images_dir(item_id)
            images_dir.mkdir()
            for i, src in enumerate(image_paths, start=1):
                src = Path(src)
                ext = src.suffix.lstrip(".") or "jpg"
                dst = images_dir / f"{i:03d}.{ext}"
                shutil.copy2(src, dst)
            has_images = True

        if video_path:
            src = Path(video_path)
            ext = src.suffix.lstrip(".") or "mp4"
            dst = item_dir / f"video.{ext}"
            shutil.copy2(src, dst)
            has_video = True

        content = kwargs.pop("content", "") or ""
        self.content_path(item_id).write_text(content, encoding="utf-8")

        item = Item(
            id=item_id,
            created_at=now,
            updated_at=now,
            type=kwargs.pop("type", "thought"),
            source=kwargs.pop("source", "telegram"),
            tags=kwargs.pop("tags", None) or [],
            status="active",
            bookmark_url=kwargs.pop("bookmark_url", None),
            telegram_message_id=kwargs.pop("telegram_message_id", None),
            has_audio=has_audio,
            has_images=has_images,
            has_video=has_video,
            content=content,
        )
        self._write_yaml(item)
        item.images = [p.name for p in self.image_files(item_id)]
        return item

    async def get(self, item_id: str) -> Item | None:
        return await asyncio.to_thread(self._read_item, item_id)

    def _read_item(self, item_id: str) -> Item | None:
        yaml_path = self.yaml_path(item_id)
        if not yaml_path.exists():
            return None
        with yaml_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        content_path = self.content_path(item_id)
        content = content_path.read_text(encoding="utf-8") if content_path.exists() else ""

        item = Item(
            id=str(data.get("id", item_id)),
            created_at=_parse_datetime(data.get("created_at", _now())),
            updated_at=_parse_datetime(data.get("updated_at", _now())),
            type=data.get("type", "thought"),
            source=data.get("source", "telegram"),
            tags=list(data.get("tags") or []),
            status=data.get("status", "active"),
            bookmark_url=data.get("bookmark_url"),
            summary=data.get("summary"),
            telegram_message_id=data.get("telegram_message_id"),
            has_audio=bool(data.get("has_audio", False)),
            has_images=bool(data.get("has_images", False)),
            has_video=bool(data.get("has_video", False)),
            content=content,
        )
        item.images = [p.name for p in self.image_files(item_id)]
        return item

    async def update(self, item_id: str, **changes) -> Item | None:
        return await asyncio.to_thread(self._update_sync, item_id, changes)

    def _update_sync(self, item_id: str, changes: dict) -> Item | None:
        item = self._read_item(item_id)
        if item is None:
            return None

        content = changes.pop("content", None)
        if content is not None:
            self.content_path(item_id).write_text(content, encoding="utf-8")
            item.content = content

        for key, value in changes.items():
            if hasattr(item, key):
                setattr(item, key, value)

        item.updated_at = _now()
        self._write_yaml(item)
        item.images = [p.name for p in self.image_files(item_id)]
        return item

    async def delete(self, item_id: str) -> bool:
        """Soft delete — set status=deleted."""
        item = await self.update(item_id, status="deleted")
        return item is not None

    async def hard_delete(self, item_id: str) -> bool:
        return await asyncio.to_thread(self._hard_delete_sync, item_id)

    def _hard_delete_sync(self, item_id: str) -> bool:
        d = self.item_dir(item_id)
        if not d.exists():
            return False
        shutil.rmtree(d)
        return True

    # ---------- iteration ----------

    def iter_ids(self) -> Iterator[str]:
        if not self.items_dir.exists():
            return
        for p in sorted(self.items_dir.iterdir()):
            if p.is_dir() and _ID_RE.match(p.name):
                yield p.name

    def _write_yaml(self, item: Item) -> None:
        with self.yaml_path(item.id).open("w", encoding="utf-8") as f:
            yaml.safe_dump(item.to_yaml_dict(), f, allow_unicode=True, sort_keys=False)


def generate_id(now: datetime | None = None) -> str:
    """Exposed for tests."""
    return _generate_id(now)
