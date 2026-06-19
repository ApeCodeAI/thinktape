"""BrainDump — main class combining ItemStore + IndexDB."""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .index import IndexDB
from .models import Item, Stats
from .store import ItemStore


class BrainDump:
    """Main facade: file-backed item store + SQLite index."""

    def __init__(self, config: Config):
        self.config = config
        self.store = ItemStore(config.items_dir)
        self.index = IndexDB(config.db_path)

    async def connect(self) -> None:
        await self.index.connect()
        # If the index is empty but items/ has data, populate it.
        async with self.index.db.execute("SELECT COUNT(*) AS n FROM items") as cur:
            row = await cur.fetchone()
            n = row["n"]
        if n == 0 and any(self.store.iter_ids()):
            await self.rebuild_index()

    async def close(self) -> None:
        await self.index.close()

    # ---------- write ----------

    async def add(
        self,
        content: str,
        *,
        type: str = "thought",
        source: str = "telegram",
        audio_path: Path | None = None,
        image_paths: list[Path] | None = None,
        video_path: Path | None = None,
        bookmark_url: str | None = None,
        tags: list[str] | None = None,
        telegram_message_id: int | None = None,
    ) -> Item:
        item = await self.store.create(
            content=content,
            type=type,
            source=source,
            audio_path=audio_path,
            image_paths=image_paths,
            video_path=video_path,
            bookmark_url=bookmark_url,
            tags=tags,
            telegram_message_id=telegram_message_id,
        )
        await self.index.upsert(item)
        return item

    async def update(self, item_id: str, **changes) -> Item | None:
        item = await self.store.update(item_id, **changes)
        if item is not None:
            await self.index.upsert(item)
        return item

    async def delete(self, item_id: str) -> bool:
        ok = await self.store.delete(item_id)
        if ok:
            item = await self.store.get(item_id)
            if item is not None:
                await self.index.upsert(item)
        return ok

    # ---------- read ----------

    async def get(self, item_id: str) -> Item | None:
        # Prefer file (source of truth) — but fall back to index if file missing.
        item = await self.store.get(item_id)
        if item is None:
            return await self.index.get(item_id)
        return item

    async def list(
        self,
        *,
        type: str | None = None,
        tag: str | None = None,
        status: str | None = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Item]:
        items = await self.index.list(
            type=type, tag=tag, status=status, limit=limit, offset=offset
        )
        # Attach image filenames (not stored in index).
        for item in items:
            item.images = [p.name for p in self.store.image_files(item.id)]
        return items

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = "active",
    ) -> list[Item]:
        items = await self.index.search(query, limit=limit, offset=offset, status=status)
        for item in items:
            item.images = [p.name for p in self.store.image_files(item.id)]
        return items

    async def stats(self) -> Stats:
        return await self.index.stats()

    async def all_tags(self) -> list[str]:
        return await self.index.all_tags()

    async def rebuild_index(self) -> int:
        items = []
        for item_id in self.store.iter_ids():
            item = await self.store.get(item_id)
            if item is not None:
                items.append(item)
        return await self.index.rebuild(items)
