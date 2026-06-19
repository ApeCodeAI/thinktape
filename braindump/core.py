"""BrainDump — main class combining ItemStore + IndexDB."""
from __future__ import annotations

from pathlib import Path

from .config import Config
from .index import IndexDB
from .links import find_concept_matches, make_snippet
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

    # ---------- links ----------

    async def get_links(self, item_id: str) -> list[dict]:
        """Outgoing links from an item with resolved matches.

        For 'item' targets: include the target item if it exists.
        For 'concept' targets: include items whose content mentions the concept text.
        """
        raw = await self.index.get_outgoing_links(item_id)
        out: list[dict] = []
        for link in raw:
            target = link["target"]
            if link["type"] == "item":
                target_item = await self.get(target)
                entry: dict = {"type": "item", "target": target}
                if target_item is not None:
                    target_item.images = [p.name for p in self.store.image_files(target)]
                    entry["item"] = _item_brief(target_item)
                out.append(entry)
            else:  # concept
                # All items matching this concept either via [[]] or text mention.
                matches = await self.get_concept_items(target, exclude_id=item_id)
                out.append({
                    "type": "concept",
                    "target": target,
                    "matches": [
                        {
                            "id": m.id,
                            "snippet": make_snippet(m.content, target),
                            "type": m.type,
                            "created_at": m.created_at.isoformat(),
                        }
                        for m in matches[:10]
                    ],
                    "match_count": len(matches),
                })
        return out

    async def get_backlinks(self, item_id: str) -> list[dict]:
        """Items that link to this item.

        Includes direct [[id]] references AND items whose [[concepts]] match
        this item's content (i.e. this item is a possible referent of a concept link).
        """
        seen: dict[str, dict] = {}

        # Direct id backlinks
        for src_id in await self.index.get_backlinks(item_id):
            src = await self.get(src_id)
            if src is None:
                continue
            seen[src_id] = {
                "id": src_id,
                "content": make_snippet(src.content, item_id),
                "link_text": item_id,
                "via": "item",
                "created_at": src.created_at.isoformat(),
            }

        # Concept backlinks: this item's content contains text matching a concept
        # that some other item has linked via [[]].
        item = await self.get(item_id)
        if item is not None and item.content:
            content_lc = item.content.lower()
            concepts = await self.index.get_all_concepts()
            for c in concepts:
                name = c["name"]
                if name.lower() not in content_lc:
                    continue
                for src_id in await self.index.get_concept_references(name):
                    if src_id == item_id or src_id in seen:
                        continue
                    src = await self.get(src_id)
                    if src is None:
                        continue
                    seen[src_id] = {
                        "id": src_id,
                        "content": make_snippet(src.content, name),
                        "link_text": name,
                        "via": "concept",
                        "created_at": src.created_at.isoformat(),
                    }

        out = list(seen.values())
        out.sort(key=lambda b: b["created_at"], reverse=True)
        return out

    async def get_concept_items(
        self, concept: str, *, exclude_id: str | None = None,
    ) -> list[Item]:
        """Items related to a concept — either contain [[concept]] OR mention the text."""
        seen: dict[str, Item] = {}

        for src_id in await self.index.get_concept_references(concept):
            if src_id == exclude_id:
                continue
            it = await self.get(src_id)
            if it is None:
                continue
            it.images = [p.name for p in self.store.image_files(it.id)]
            seen[it.id] = it

        # Text-content matches (case-insensitive)
        text_matches = await self._search_text_contains(concept, limit=200)
        for it in text_matches:
            if it.id == exclude_id or it.id in seen:
                continue
            it.images = [p.name for p in self.store.image_files(it.id)]
            seen[it.id] = it

        items = list(seen.values())
        items.sort(key=lambda i: i.created_at, reverse=True)
        return items

    async def all_concepts(self) -> list[dict]:
        return await self.index.get_all_concepts()

    async def _search_text_contains(self, needle: str, *, limit: int = 200) -> list[Item]:
        """Case-insensitive substring search on item content (active only)."""
        needle = (needle or "").strip()
        if not needle:
            return []
        like = f"%{needle}%"
        async with self.index.db.execute(
            """
            SELECT * FROM items
            WHERE status = 'active' AND LOWER(content) LIKE LOWER(?)
            ORDER BY created_at DESC LIMIT ?
            """,
            (like, limit),
        ) as cur:
            rows = await cur.fetchall()
        from .index import _row_to_item  # local import to avoid cycle at module load
        return [_row_to_item(r) for r in rows]


def _item_brief(item: Item) -> dict:
    """Compact dict for embedding inside link responses."""
    content = item.content or ""
    if len(content) > 200:
        content = content[:200] + "…"
    return {
        "id": item.id,
        "type": item.type,
        "created_at": item.created_at.isoformat(),
        "content": content,
        "tags": item.tags,
    }
