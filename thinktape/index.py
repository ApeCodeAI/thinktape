"""Canonical SQLite storage and derived query indexes."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

import aiosqlite

from .links import extract_links
from .models import Asset, Item, Stats

_TZ_CST = timezone(timedelta(hours=8))
STORAGE_CONTRACT_KEY = "storage_contract"
STORAGE_CONTRACT_VALUE = "sqlite-db-first-v1"


@dataclass
class TransactionState:
    committed: bool = False


class ItemAlreadyExistsError(RuntimeError):
    """A new item could not reserve its generated primary key."""


SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    type          TEXT NOT NULL,
    source        TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    tags          TEXT NOT NULL DEFAULT '[]',
    bookmark_url  TEXT,
    summary       TEXT,
    has_audio     INTEGER NOT NULL DEFAULT 0,
    has_images    INTEGER NOT NULL DEFAULT 0,
    has_video     INTEGER NOT NULL DEFAULT 0,
    telegram_message_id INTEGER,
    content       TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_items_created_at ON items(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_type ON items(type);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);

CREATE TABLE IF NOT EXISTS item_tags (
    item_id TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (item_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_item_tags_tag ON item_tags(tag);

CREATE TABLE IF NOT EXISTS assets (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id           TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    path              TEXT NOT NULL UNIQUE,
    kind              TEXT NOT NULL CHECK(kind IN ('audio', 'video', 'image')),
    sha256            TEXT NOT NULL,
    byte_size         INTEGER NOT NULL,
    mime_type         TEXT,
    original_filename TEXT,
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_item_kind ON assets(item_id, kind, id);

CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
    id UNINDEXED,
    content,
    tags,
    bookmark_url,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS links (
    source_id   TEXT NOT NULL,
    target      TEXT NOT NULL,
    target_type TEXT NOT NULL,
    PRIMARY KEY (source_id, target)
);
CREATE INDEX IF NOT EXISTS idx_links_target ON links(target);
CREATE INDEX IF NOT EXISTS idx_links_target_type ON links(target_type);
"""


def _row_to_item(row: aiosqlite.Row) -> Item:
    return Item(
        id=row["id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
        type=row["type"],
        source=row["source"],
        status=row["status"],
        tags=json.loads(row["tags"] or "[]"),
        bookmark_url=row["bookmark_url"],
        summary=row["summary"],
        has_audio=bool(row["has_audio"]),
        has_images=bool(row["has_images"]),
        has_video=bool(row["has_video"]),
        telegram_message_id=row["telegram_message_id"],
        content=row["content"] or "",
    )


class IndexDB:
    """Async SQLite index. One long-lived connection per process."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._db is not None:
            return
        existed = self.db_path.exists()
        if existed:
            marker = await asyncio.to_thread(self._read_storage_contract, self.db_path)
            if marker != STORAGE_CONTRACT_VALUE:
                raise RuntimeError("database has no completed DB-first storage contract")
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(SCHEMA)
        if not existed:
            await self._set_storage_contract_unlocked()
        await self._rebuild_derived()
        await self._db.commit()

    async def connect_for_migration(self, *, dry_run: bool) -> None:
        """Open current storage for explicit migration without trusting its marker."""
        if self._db is not None:
            return
        if dry_run:
            self._db = await aiosqlite.connect(":memory:")
            if self.db_path.exists():
                source = await aiosqlite.connect(
                    f"file:{self.db_path.resolve()}?mode=ro", uri=True,
                )
                try:
                    await source.backup(self._db)
                finally:
                    await source.close()
        else:
            self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(SCHEMA)
        await self._rebuild_derived()
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    @property
    def db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("IndexDB not connected — call connect() first")
        return self._db

    @property
    def is_connected(self) -> bool:
        return self._db is not None

    @staticmethod
    def _read_storage_contract(db_path: Path) -> str | None:
        import sqlite3

        connection = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        try:
            row = connection.execute(
                "SELECT value FROM storage_metadata WHERE key = ?",
                (STORAGE_CONTRACT_KEY,),
            ).fetchone()
        except sqlite3.DatabaseError:
            return None
        finally:
            connection.close()
        return row[0] if row else None

    async def set_storage_contract(self) -> None:
        async with self.transaction():
            await self._set_storage_contract_unlocked()

    async def _set_storage_contract_unlocked(self) -> None:
        await self.db.execute(
            "INSERT OR REPLACE INTO storage_metadata(key, value) VALUES(?, ?)",
            (STORAGE_CONTRACT_KEY, STORAGE_CONTRACT_VALUE),
        )

    @asynccontextmanager
    async def transaction(self):
        """Serialize a complete write transaction on the shared connection."""
        async with self._write_lock:
            await self.db.execute("BEGIN IMMEDIATE")
            state = TransactionState()
            try:
                yield state
            except BaseException:
                await self._finish_db_call(self.db.rollback())
                raise
            else:
                commit_task = asyncio.create_task(self.db.commit())
                cancellation: asyncio.CancelledError | None = None
                try:
                    while not commit_task.done():
                        try:
                            await asyncio.shield(commit_task)
                        except asyncio.CancelledError as exc:
                            cancellation = exc
                    commit_task.result()
                except BaseException:
                    await self._finish_db_call(self.db.rollback())
                    raise
                state.committed = True
                if cancellation is not None:
                    raise cancellation

    @staticmethod
    async def _finish_db_call(coro) -> None:
        task = asyncio.create_task(coro)
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        await task

    # ---------- upsert / delete ----------

    async def insert(self, item: Item) -> None:
        async with self.transaction():
            await self._insert(item)

    async def _insert(self, item: Item) -> None:
        try:
            await self.db.execute(
                """
                INSERT INTO items(id, created_at, updated_at, type, source, status, tags,
                                  bookmark_url, summary, has_audio, has_images, has_video,
                                  telegram_message_id, content)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.created_at.isoformat(),
                    item.updated_at.isoformat(),
                    item.type,
                    item.source,
                    item.status,
                    json.dumps(item.tags, ensure_ascii=False),
                    item.bookmark_url,
                    item.summary,
                    int(item.has_audio),
                    int(item.has_images),
                    int(item.has_video),
                    item.telegram_message_id,
                    item.content,
                ),
            )
        except aiosqlite.IntegrityError as exc:
            if exc.sqlite_errorcode in {
                sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY,
                sqlite3.SQLITE_CONSTRAINT_UNIQUE,
            }:
                raise ItemAlreadyExistsError(item.id) from exc
            raise
        await self._refresh_derived(item)

    async def update(self, item: Item) -> bool:
        async with self.transaction():
            return await self._update(item)

    async def _update(self, item: Item) -> bool:
        cursor = await self.db.execute(
            """
            UPDATE items SET
                updated_at = ?,
                type = ?,
                source = ?,
                status = ?,
                tags = ?,
                bookmark_url = ?,
                summary = ?,
                has_audio = ?,
                has_images = ?,
                has_video = ?,
                telegram_message_id = ?,
                content = ?
            WHERE id = ?
            """,
            (
                item.updated_at.isoformat(),
                item.type,
                item.source,
                item.status,
                json.dumps(item.tags, ensure_ascii=False),
                item.bookmark_url,
                item.summary,
                int(item.has_audio),
                int(item.has_images),
                int(item.has_video),
                item.telegram_message_id,
                item.content,
                item.id,
            ),
        )
        if cursor.rowcount == 0:
            return False
        await self._refresh_derived(item)
        return True

    async def upsert(self, item: Item) -> None:
        async with self.transaction():
            await self._upsert(item)

    async def _upsert(self, item: Item) -> None:
        # Index the union of explicit tags + inline #hashtags so filtering,
        # stats, all_tags and FTS all see hashtags typed into the body.
        all_tags = item.all_tags
        await self.db.execute(
            """
            INSERT INTO items(id, created_at, updated_at, type, source, status, tags,
                              bookmark_url, summary, has_audio, has_images, has_video,
                              telegram_message_id, content)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                updated_at = excluded.updated_at,
                type = excluded.type,
                source = excluded.source,
                status = excluded.status,
                tags = excluded.tags,
                bookmark_url = excluded.bookmark_url,
                summary = excluded.summary,
                has_audio = excluded.has_audio,
                has_images = excluded.has_images,
                has_video = excluded.has_video,
                telegram_message_id = excluded.telegram_message_id,
                content = excluded.content
            """,
            (
                item.id,
                item.created_at.isoformat(),
                item.updated_at.isoformat(),
                item.type,
                item.source,
                item.status,
                json.dumps(item.tags, ensure_ascii=False),
                item.bookmark_url,
                item.summary,
                int(item.has_audio),
                int(item.has_images),
                int(item.has_video),
                item.telegram_message_id,
                item.content,
            ),
        )
        await self._refresh_derived(item)

    async def _refresh_derived(self, item: Item) -> None:
        all_tags = item.all_tags
        await self.db.execute("DELETE FROM items_fts WHERE id = ?", (item.id,))
        await self.db.execute(
            "INSERT INTO items_fts(id, content, tags, bookmark_url) VALUES(?, ?, ?, ?)",
            (item.id, item.content, " ".join(all_tags), item.bookmark_url or ""),
        )
        await self.db.execute("DELETE FROM item_tags WHERE item_id = ?", (item.id,))
        for tag in all_tags:
            await self.db.execute(
                "INSERT OR IGNORE INTO item_tags(item_id, tag) VALUES(?, ?)",
                (item.id, tag),
            )
        await self._refresh_links(item.id, item.content)

    async def rebuild_derived(self) -> int:
        """Rebuild query-only tables from canonical SQLite item rows."""
        async with self.transaction():
            return await self._rebuild_derived()

    async def _rebuild_derived(self) -> int:
        await self.db.execute("DELETE FROM items_fts")
        await self.db.execute("DELETE FROM item_tags")
        await self.db.execute("DELETE FROM links")
        async with self.db.execute("SELECT * FROM items") as cur:
            items = [_row_to_item(row) for row in await cur.fetchall()]
        for item in items:
            await self._refresh_derived(item)
        return len(items)

    async def insert_assets(self, assets: Iterable[Asset]) -> None:
        async with self.transaction():
            await self._insert_assets(assets)

    async def _insert_assets(self, assets: Iterable[Asset]) -> None:
        for asset in assets:
            cur = await self.db.execute(
                """
                INSERT INTO assets(item_id, path, kind, sha256, byte_size, mime_type,
                                   original_filename, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset.item_id,
                    asset.path,
                    asset.kind,
                    asset.sha256,
                    asset.byte_size,
                    asset.mime_type,
                    asset.original_filename,
                    asset.created_at.isoformat(),
                ),
            )
            asset.id = cur.lastrowid

    async def list_assets(self, item_id: str, *, kind: str | None = None) -> list[Asset]:
        sql = "SELECT * FROM assets WHERE item_id = ?"
        params: list = [item_id]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY id"
        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [
            Asset(
                id=row["id"], item_id=row["item_id"], path=row["path"],
                kind=row["kind"], sha256=row["sha256"], byte_size=row["byte_size"],
                mime_type=row["mime_type"], original_filename=row["original_filename"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    async def delete(self, item_id: str) -> None:
        async with self.transaction():
            await self._delete(item_id)

    async def _delete(self, item_id: str) -> None:
        await self.db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        await self.db.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
        await self.db.execute("DELETE FROM item_tags WHERE item_id = ?", (item_id,))
        await self.db.execute("DELETE FROM links WHERE source_id = ?", (item_id,))

    # ---------- links ----------

    async def _refresh_links(self, item_id: str, content: str) -> None:
        await self.db.execute("DELETE FROM links WHERE source_id = ?", (item_id,))
        for link in extract_links(content):
            await self.db.execute(
                "INSERT OR IGNORE INTO links(source_id, target, target_type) VALUES(?, ?, ?)",
                (item_id, link["target"], link["type"]),
            )

    async def get_outgoing_links(self, item_id: str) -> list[dict[str, str]]:
        async with self.db.execute(
            "SELECT target, target_type FROM links WHERE source_id = ? ORDER BY target",
            (item_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [{"type": r["target_type"], "target": r["target"]} for r in rows]

    async def get_backlinks(self, item_id: str) -> list[str]:
        """Items that link to this item by id (target_type='item')."""
        async with self.db.execute(
            """
            SELECT DISTINCT source_id FROM links
            WHERE target = ? AND target_type = 'item' AND source_id != ?
            """,
            (item_id, item_id),
        ) as cur:
            rows = await cur.fetchall()
        return [r["source_id"] for r in rows]

    async def get_concept_references(self, concept: str) -> list[str]:
        """Items that contain [[concept]] in their content."""
        async with self.db.execute(
            """
            SELECT DISTINCT source_id FROM links
            WHERE target = ? AND target_type = 'concept'
            """,
            (concept,),
        ) as cur:
            rows = await cur.fetchall()
        return [r["source_id"] for r in rows]

    async def get_all_concepts(self) -> list[dict]:
        """All unique concepts referenced in [[]], with usage counts."""
        async with self.db.execute(
            """
            SELECT target AS name, COUNT(DISTINCT source_id) AS count
            FROM links
            WHERE target_type = 'concept'
            GROUP BY target
            ORDER BY count DESC, target ASC
            """
        ) as cur:
            rows = await cur.fetchall()
        return [{"name": r["name"], "count": r["count"]} for r in rows]

    # ---------- queries ----------

    async def get(self, item_id: str) -> Item | None:
        async with self.db.execute("SELECT * FROM items WHERE id = ?", (item_id,)) as cur:
            row = await cur.fetchone()
        return _row_to_item(row) if row else None

    async def item_ids(self) -> list[str]:
        async with self.db.execute("SELECT id FROM items ORDER BY id") as cur:
            return [row["id"] for row in await cur.fetchall()]

    async def list(
        self,
        *,
        type: str | None = None,
        tag: str | None = None,
        status: str | None = "active",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Item]:
        sql = "SELECT * FROM items WHERE 1=1"
        params: list = []
        if status:
            sql += " AND status = ?"
            params.append(status)
        if type:
            sql += " AND type = ?"
            params.append(type)
        if tag:
            sql += " AND EXISTS (SELECT 1 FROM item_tags WHERE item_tags.item_id = items.id AND item_tags.tag = ?)"
            params.append(tag)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [_row_to_item(r) for r in rows]

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = "active",
    ) -> list[Item]:
        if not query.strip():
            return await self.list(limit=limit, offset=offset, status=status)
        # Tokenize and wrap each token as a quoted prefix term: "tok"*
        tokens = [t for t in query.split() if t]
        fts_q = " ".join(f'"{t.replace(chr(34), "")}"*' for t in tokens)
        sql = """
            SELECT items.* FROM items
            JOIN items_fts ON items.id = items_fts.id
            WHERE items_fts MATCH ?
        """
        params: list = [fts_q]
        if status:
            sql += " AND items.status = ?"
            params.append(status)
        sql += " ORDER BY items.created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        try:
            async with self.db.execute(sql, params) as cur:
                rows = await cur.fetchall()
        except aiosqlite.OperationalError:
            # Fall back to LIKE search if FTS query is malformed.
            return await self._like_search(query, limit=limit, offset=offset, status=status)
        return [_row_to_item(r) for r in rows]

    async def _like_search(self, query: str, *, limit: int, offset: int, status: str | None) -> list[Item]:
        sql = "SELECT * FROM items WHERE content LIKE ?"
        params: list = [f"%{query}%"]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        async with self.db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [_row_to_item(r) for r in rows]

    # ---------- stats ----------

    async def stats(self) -> Stats:
        async with self.db.execute(
            "SELECT COUNT(*) AS n FROM items WHERE status = 'active'"
        ) as cur:
            total = (await cur.fetchone())["n"]

        today_start = datetime.now(_TZ_CST).replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.db.execute(
            "SELECT COUNT(*) AS n FROM items WHERE status = 'active' AND created_at >= ?",
            (today_start.isoformat(),),
        ) as cur:
            today = (await cur.fetchone())["n"]

        async with self.db.execute(
            "SELECT type, COUNT(*) AS n FROM items WHERE status = 'active' GROUP BY type"
        ) as cur:
            by_type = {row["type"]: row["n"] for row in await cur.fetchall()}

        async with self.db.execute(
            """
            SELECT item_tags.tag, COUNT(*) AS n
            FROM item_tags JOIN items ON items.id = item_tags.item_id
            WHERE items.status = 'active'
            GROUP BY item_tags.tag
            """
        ) as cur:
            by_tag = {row["tag"]: row["n"] for row in await cur.fetchall()}

        return Stats(total=total, today=today, by_type=by_type, by_tag=by_tag)

    async def all_tags(self) -> list[str]:
        async with self.db.execute(
            """
            SELECT DISTINCT item_tags.tag
            FROM item_tags JOIN items ON items.id = item_tags.item_id
            WHERE items.status = 'active'
            ORDER BY item_tags.tag
            """
        ) as cur:
            return [row["tag"] for row in await cur.fetchall()]
