"""Pydantic models for thinktape."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .tags import extract_hashtags

ItemType = Literal["thought", "bookmark", "note"]
ItemStatus = Literal["active", "archived", "deleted"]
ItemSource = Literal["telegram", "web", "cli", "api", "app"]
AssetKind = Literal["audio", "video", "image"]


class Asset(BaseModel):
    """An immutable media file referenced by SQLite."""

    id: int | None = None
    item_id: str
    path: str
    kind: AssetKind
    sha256: str
    byte_size: int
    mime_type: str | None = None
    original_filename: str | None = None
    created_at: datetime


class Item(BaseModel):
    """An item in the thinktape store."""

    id: str
    created_at: datetime
    updated_at: datetime
    type: ItemType = "thought"
    source: ItemSource = "telegram"
    tags: list[str] = Field(default_factory=list)
    status: ItemStatus = "active"

    bookmark_url: str | None = None
    summary: str | None = None
    telegram_message_id: int | None = None

    has_audio: bool = False
    has_images: bool = False
    has_video: bool = False

    # Content is canonical in SQLite; image names are derived from asset rows.
    content: str = ""
    images: list[str] = Field(default_factory=list)

    @property
    def all_tags(self) -> list[str]:
        """Explicit tags unioned with #hashtags parsed from content.

        First-seen order, de-duplicated. Used for indexing and display;
        SQLite persists the explicit tags alongside canonical content.
        """
        out: list[str] = []
        seen: set[str] = set()
        for tag in (*self.tags, *extract_hashtags(self.content)):
            if tag and tag not in seen:
                seen.add(tag)
                out.append(tag)
        return out

    def to_yaml_dict(self) -> dict:
        """Serialize for the read-only legacy migration adapter."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "type": self.type,
            "source": self.source,
            "tags": self.tags,
            "status": self.status,
            "bookmark_url": self.bookmark_url,
            "summary": self.summary,
            "telegram_message_id": self.telegram_message_id,
            "has_audio": self.has_audio,
            "has_images": self.has_images,
            "has_video": self.has_video,
        }


class Stats(BaseModel):
    total: int
    today: int
    by_type: dict[str, int]
    by_tag: dict[str, int]
