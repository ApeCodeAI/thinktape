"""SQLite index — built from items/ on the fly, can always be rebuilt."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Iterable

import aiosqlite

from .links import extract_links
from .models import Item, Stats

_TZ_CST = timezone(timedelta(hours=8))


SCHEMA = """
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

    async def connect(self) -> None:
        if self._db is not None:
            return
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
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

    # ---------- upsert / delete ----------

    async def upsert(self, item: Item) -> None:
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
        await self.db.execute("DELETE FROM items_fts WHERE id = ?", (item.id,))
        await self.db.execute(
            "INSERT INTO items_fts(id, content, tags, bookmark_url) VALUES(?, ?, ?, ?)",
            (item.id, item.content, " ".join(item.tags), item.bookmark_url or ""),
        )
        await self._refresh_links(item.id, item.content)
        await self.db.commit()

    async def delete(self, item_id: str) -> None:
        await self.db.execute("DELETE FROM items WHERE id = ?", (item_id,))
        await self.db.execute("DELETE FROM items_fts WHERE id = ?", (item_id,))
        await self.db.execute("DELETE FROM links WHERE source_id = ?", (item_id,))
        await self.db.commit()

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
            # tags column stores JSON list. crude LIKE match is OK for an index.
            sql += " AND tags LIKE ?"
            params.append(f'%"{tag}"%')
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

        # Tag breakdown — manual aggregation since tags is JSON.
        by_tag: dict[str, int] = {}
        async with self.db.execute("SELECT tags FROM items WHERE status = 'active'") as cur:
            async for row in cur:
                for tag in json.loads(row["tags"] or "[]"):
                    by_tag[tag] = by_tag.get(tag, 0) + 1

        return Stats(total=total, today=today, by_type=by_type, by_tag=by_tag)

    async def all_tags(self) -> list[str]:
        seen: set[str] = set()
        async with self.db.execute("SELECT tags FROM items WHERE status = 'active'") as cur:
            async for row in cur:
                for tag in json.loads(row["tags"] or "[]"):
                    seen.add(tag)
        return sorted(seen)

    # ---------- rebuild ----------

    async def rebuild(self, items: Iterable[Item]) -> int:
        await self.db.execute("DELETE FROM items")
        await self.db.execute("DELETE FROM items_fts")
        await self.db.execute("DELETE FROM links")
        await self.db.commit()
        n = 0
        for item in items:
            await self.upsert(item)
            n += 1
        return n
