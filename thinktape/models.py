"""Pydantic models for thinktape."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ItemType = Literal["thought", "bookmark", "note"]
ItemStatus = Literal["active", "archived", "deleted"]
ItemSource = Literal["telegram", "web", "cli", "api"]


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

    # Not stored in item.yaml — populated when reading.
    content: str = ""
    images: list[str] = Field(default_factory=list)

    def to_yaml_dict(self) -> dict:
        """Serialize for item.yaml (excludes content and images list)."""
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
