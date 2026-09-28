"""ThinkTape — SQLite-backed application facade."""
from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .index import (
    IndexDB,
    ItemAlreadyExistsError,
    RecordingConflictError,
    STORAGE_CONTRACT_VALUE,
)
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


_RECORDING_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAX_TRANSCRIPTION_ATTEMPTS = 3


@dataclass(frozen=True)
class RecordingIngestResult:
    item: Item
    recording: dict
    created: bool


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

    async def ingest_recording(
        self,
        recording_id: str,
        audio_path: Path,
        *,
        content: str = "",
        type: str = "thought",
        source: str = "app",
        tags: list[str] | None = None,
    ) -> RecordingIngestResult:
        """Durably store one client recording, with stable-id replay semantics."""
        if not _RECORDING_ID_RE.fullmatch(recording_id or ""):
            raise ValueError("invalid recording_id")
        audio_path = Path(audio_path)
        try:
            checksum, byte_size = await asyncio.to_thread(
                self.asset_store._digest_file, audio_path,
            )
        except FileNotFoundError as exc:
            raise ValueError("audio file is missing") from exc
        if byte_size <= 0:
            raise ValueError("audio must not be empty")
        now = _now()
        staged = None
        transaction = None
        result: RecordingIngestResult | None = None
        try:
            async with self.index.transaction() as transaction:
                existing = await self.index.get_recording(recording_id)
                if existing is not None:
                    if (
                        existing["checksum"] != checksum
                        or existing["byte_size"] != byte_size
                    ):
                        raise RecordingConflictError(recording_id)
                    item = await self.index.get(existing["item_id"])
                    if item is None or item.status != "active":
                        raise AssetIntegrityError("recording item unavailable")
                    assets = await self.index.list_assets(item.id, kind="audio")
                    if len(assets) != 1 or assets[0].sha256 != checksum:
                        raise AssetIntegrityError("recording asset integrity check failed")
                    await self.asset_store.verified_path(assets[0])
                    await self._attach_assets(item)
                    result = RecordingIngestResult(item, existing, False)
                else:
                    body = content if content.strip() else "[转写中…]"
                    item = None
                    while True:
                        item_id = generate_id(now)
                        candidate = Item(
                            id=item_id,
                            created_at=now,
                            updated_at=now,
                            type=type,
                            source=source,
                            tags=tags or [],
                            status="active",
                            content=body,
                        )
                        staged = await self.asset_store.stage(
                            item_id,
                            audio_path=audio_path,
                            created_at=now,
                        )
                        candidate.has_audio = True
                        try:
                            await self.index._insert(candidate)
                        except ItemAlreadyExistsError:
                            await self.asset_store.discard(staged)
                            staged = None
                            continue
                        item = candidate
                        break
                    if len(staged.assets) != 1 or (
                        staged.assets[0].sha256 != checksum
                        or staged.assets[0].byte_size != byte_size
                    ):
                        raise ValueError("audio changed during ingestion")
                    await self.index._insert_assets(staged.assets)
                    await self.index._insert_recording(
                        recording_id,
                        item.id,
                        checksum,
                        byte_size,
                        transcription_status="completed" if content.strip() else "pending",
                        created_at=now,
                    )
                    await self.asset_store.promote(staged)
                    receipt = await self.index.get_recording(recording_id)
                    assert receipt is not None
                    result = RecordingIngestResult(item, receipt, True)
        except BaseException:
            if staged is not None and (transaction is None or not transaction.committed):
                await self.asset_store.discard(staged)
            raise
        assert result is not None
        return result

    async def get_recording(self, recording_id: str) -> dict | None:
        return await self.index.get_recording(recording_id)

    async def queue_recording(self, recording_id: str) -> dict | None:
        """Queue a pending recording once; a worker can recover missed notifications."""
        async with self.index.transaction():
            async with self.index.db.execute(
                "SELECT * FROM recordings WHERE recording_id = ?", (recording_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            if row["transcription_status"] == "pending" and row["attempts"] < MAX_TRANSCRIPTION_ATTEMPTS:
                await self.index.db.execute(
                    "UPDATE recordings SET transcription_status = 'queued', updated_at = ? WHERE recording_id = ?",
                    (_now().isoformat(), recording_id),
                )
        return await self.index.get_recording(recording_id)

    async def retry_recording(self, recording_id: str, *, worker_available: bool) -> dict | None:
        """Reset a failed job once, without allowing permanent retry loops."""
        async with self.index.transaction():
            async with self.index.db.execute(
                "SELECT * FROM recordings WHERE recording_id = ?", (recording_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            if row["transcription_status"] in {"completed", "queued", "running"}:
                return self.index._recording_dict(row)
            if row["attempts"] >= MAX_TRANSCRIPTION_ATTEMPTS:
                raise RuntimeError("transcription retry limit reached")
            status = "queued" if worker_available else "pending"
            await self.index.db.execute(
                """
                UPDATE recordings
                SET transcription_status = ?, last_error = NULL, updated_at = ?
                WHERE recording_id = ?
                """,
                (status, _now().isoformat(), recording_id),
            )
        return await self.index.get_recording(recording_id)

    async def start_recording_transcription(self, recording_id: str) -> dict | None:
        """Claim one queued job and increment its durable attempt counter."""
        async with self.index.transaction():
            async with self.index.db.execute(
                "SELECT * FROM recordings WHERE recording_id = ?", (recording_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            if row["transcription_status"] != "queued":
                return None
            if row["attempts"] >= MAX_TRANSCRIPTION_ATTEMPTS:
                await self.index.db.execute(
                    "UPDATE recordings SET transcription_status = 'failed', last_error = ?, updated_at = ? WHERE recording_id = ?",
                    ("transcription retry limit reached", _now().isoformat(), recording_id),
                )
                return None
            await self.index.db.execute(
                """
                UPDATE recordings
                SET transcription_status = 'running', attempts = attempts + 1,
                    last_error = NULL, updated_at = ?
                WHERE recording_id = ? AND transcription_status = 'queued'
                """,
                (_now().isoformat(), recording_id),
            )
            async with self.index.db.execute(
                "SELECT * FROM recordings WHERE recording_id = ?", (recording_id,)
            ) as cur:
                claimed = self.index._recording_dict(await cur.fetchone())
        return claimed

    async def finish_recording_transcription(
        self, recording_id: str, *, error: str | None = None,
    ) -> dict | None:
        async with self.index.transaction():
            await self.index.db.execute(
                """UPDATE recordings SET transcription_status = ?, last_error = ?, updated_at = ?
                   WHERE recording_id = ? AND transcription_status = 'running'""",
                ("failed" if error else "completed", error, _now().isoformat(), recording_id),
            )
        return await self.index.get_recording(recording_id)

    async def update_content_if_pending(self, item_id: str, content: str) -> bool:
        """Never replace text entered while a transcription job was running."""
        async with self.index.transaction():
            item = await self.index.get(item_id)
            if item is None or (item.content and not item.content.startswith("[转写中")):
                return False
            item.content = content
            item.updated_at = _now()
            return await self.index._update(item)

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
