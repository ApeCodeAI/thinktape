"""ThinkTape — SQLite-backed application facade."""
from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .index import IndexDB, ItemAlreadyExistsError, STORAGE_CONTRACT_VALUE
from .links import find_concept_matches, make_snippet
from .models import Asset, Item, Stats
from .store import (
    AssetIntegrityError,
    AssetStore,
    ItemStore,
    generate_id,
    validate_item_id,
)


_TZ_CST = timezone(timedelta(hours=8))


class MigrationRequiredError(RuntimeError):
    """Raised when legacy or unmarked storage needs explicit migration."""


def _now() -> datetime:
    return datetime.now(_TZ_CST)


class ThinkTape:
    """Main facade with SQLite as the canonical logical item store."""

    def __init__(self, config: Config):
        self.config = config
        self.store = ItemStore(config.items_dir)
        self.asset_store = AssetStore(config.data_dir)
        self.index = IndexDB(config.db_path)

    async def connect(self) -> None:
        if not self.config.db_path.exists() and any(self.store.iter_ids()):
            raise MigrationRequiredError(
                "legacy storage migration required; run `thinktape migrate-legacy --dry-run` "
                "then `thinktape migrate-legacy --apply`"
            )
        try:
            await self.index.connect()
        except RuntimeError as exc:
            if "storage contract" not in str(exc):
                raise
            raise MigrationRequiredError(
                "database migration required; run `thinktape migrate-legacy --dry-run` "
                "then `thinktape migrate-legacy --apply`"
            ) from exc
        await self._recover_hard_deletes()

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
        now = _now()
        staged = None
        transaction = None
        try:
            async with self.index.transaction() as transaction:
                while True:
                    item_id = generate_id(now)
                    item = Item(
                        id=item_id,
                        created_at=now,
                        updated_at=now,
                        type=type,
                        source=source,
                        tags=tags or [],
                        status="active",
                        bookmark_url=bookmark_url,
                        telegram_message_id=telegram_message_id,
                        content=content or "",
                    )
                    staged = await self.asset_store.stage(
                        item_id,
                        audio_path=audio_path,
                        image_paths=image_paths,
                        video_path=video_path,
                        created_at=now,
                    )
                    item.has_audio = any(a.kind == "audio" for a in staged.assets)
                    item.has_images = any(a.kind == "image" for a in staged.assets)
                    item.has_video = any(a.kind == "video" for a in staged.assets)
                    item.images = [Path(a.path).name for a in staged.assets if a.kind == "image"]
                    try:
                        await self.index._insert(item)
                    except ItemAlreadyExistsError:
                        await self.asset_store.discard(staged)
                        staged = None
                        continue
                    break
                await self.index._insert_assets(staged.assets)
                await self.asset_store.promote(staged)
        except BaseException:
            if staged is not None and (transaction is None or not transaction.committed):
                await self.asset_store.discard(staged)
            raise
        return item

    async def update(self, item_id: str, **changes) -> Item | None:
        async with self.index.transaction():
            item = await self.index.get(item_id)
            if item is None:
                return None
            for key, value in changes.items():
                if hasattr(item, key):
                    setattr(item, key, value)
            item.updated_at = _now()
            if not await self.index._update(item):
                return None
        await self._attach_assets(item)
        return item

    async def delete(self, item_id: str) -> bool:
        return await self.update(item_id, status="deleted") is not None

    async def hard_delete(self, item_id: str) -> bool:
        if await self.index.get(item_id) is None:
            return False
        validate_item_id(item_id)
        for asset in await self.index.list_assets(item_id):
            self.asset_store.path_for(asset)
        asset_dir = self.config.assets_dir / item_id
        staged_delete = self.config.assets_dir / ".trash" / item_id
        moved = False
        transaction = None
        try:
            async with self.index.transaction() as transaction:
                if asset_dir.exists():
                    staged_delete.parent.mkdir(parents=True, exist_ok=True)
                    if staged_delete.exists():
                        raise FileExistsError(staged_delete)
                    asset_dir.replace(staged_delete)
                    moved = True
                await self.index._delete(item_id)
        except BaseException:
            if moved and transaction is not None and not transaction.committed and staged_delete.exists():
                staged_delete.replace(asset_dir)
            raise
        if moved:
            import asyncio
            import shutil

            await asyncio.to_thread(shutil.rmtree, staged_delete, True)
            try:
                staged_delete.parent.rmdir()
            except OSError:
                pass
        return True

    async def _recover_hard_deletes(self) -> None:
        """Resolve crash remnants using the canonical row as the commit record."""
        trash_root = self.config.assets_dir / ".trash"
        if trash_root.is_symlink() or not trash_root.is_dir():
            return
        for staged_delete in list(trash_root.iterdir()):
            if staged_delete.is_symlink() or not staged_delete.is_dir():
                continue
            item_id = staged_delete.name
            asset_dir = self.config.assets_dir / item_id
            if await self.index.get(item_id) is not None:
                if asset_dir.exists():
                    raise RuntimeError(
                        f"hard-delete recovery conflict for {item_id}: both asset and trash directories exist"
                    )
                staged_delete.replace(asset_dir)
            else:
                await asyncio.to_thread(shutil.rmtree, staged_delete)
        try:
            trash_root.rmdir()
        except OSError:
            pass

    # ---------- read ----------

    async def get(self, item_id: str) -> Item | None:
        item = await self.index.get(item_id)
        if item is not None:
            await self._attach_assets(item)
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
        for item in items:
            await self._attach_assets(item)
            item.tags = item.all_tags
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
            await self._attach_assets(item)
            item.tags = item.all_tags
        return items

    async def list_assets(self, item_id: str, *, kind: str | None = None) -> list[Asset]:
        return await self.index.list_assets(item_id, kind=kind)

    async def media_file(self, item_id: str, kind: str) -> Path | None:
        assets = await self.list_assets(item_id, kind=kind)
        if not assets:
            return None
        return await self.asset_store.verified_path(assets[0])

    async def image_file(self, item_id: str, name: str) -> Path | None:
        for asset in await self.list_assets(item_id, kind="image"):
            if Path(asset.path).name != name:
                continue
            return await self.asset_store.verified_path(asset)
        return None

    async def _attach_assets(self, item: Item) -> None:
        assets = await self.list_assets(item.id)
        item.has_audio = any(a.kind == "audio" for a in assets)
        item.has_images = any(a.kind == "image" for a in assets)
        item.has_video = any(a.kind == "video" for a in assets)
        item.images = [Path(a.path).name for a in assets if a.kind == "image"]

    async def stats(self) -> Stats:
        return await self.index.stats()

    async def all_tags(self) -> list[str]:
        return await self.index.all_tags()

    async def migrate_legacy(self, *, dry_run: bool = True) -> dict:
        """Explicitly import the read-only legacy ``items/`` tree."""
        from .migrate import LegacyMigrator

        verify_preexisting = (
            self.config.db_path.exists()
            and IndexDB._read_storage_contract(self.config.db_path) != STORAGE_CONTRACT_VALUE
        )
        opened_here = not self.index.is_connected
        if opened_here:
            await self.index.connect_for_migration(dry_run=dry_run)
        try:
            report = await LegacyMigrator(self).run(
                dry_run=dry_run,
                verify_preexisting=verify_preexisting,
            )
            if not dry_run and report["ok"]:
                await self.index.set_storage_contract()
            return report
        finally:
            if opened_here:
                await self.index.close()

    async def rebuild_index(self) -> int:
        """Rebuild query-only indexes from canonical SQLite item rows."""
        return await self.index.rebuild_derived()

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
                            "images": m.images,
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
            seen[it.id] = it

        # Text-content matches (case-insensitive)
        text_matches = await self._search_text_contains(concept, limit=200)
        for it in text_matches:
            if it.id == exclude_id or it.id in seen:
                continue
            await self._attach_assets(it)
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
        "tags": item.all_tags,
    }
