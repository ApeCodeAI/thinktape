"""Web routes — API endpoints for the React SPA frontend."""

import os
import re
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from braindump.config import get_config, get_timezone
from braindump.database import get_db

# FTS5 special characters that need escaping
_FTS_SPECIAL = re.compile(r'["\*\(\)\-\^]')


def _sanitize_fts_query(q: str) -> str:
    """Escape special FTS5 characters and wrap each token in double quotes."""
    q = q.strip()
    if not q:
        return q
    q = _FTS_SPECIAL.sub(" ", q)
    tokens = q.split()
    return " ".join(f'"{t}"' for t in tokens if t)


router = APIRouter()


# ── Request models ──────────────────────────────────────────────

class CreateNoteRequest(BaseModel):
    content: str
    tags: str = ""


class UpdateNoteRequest(BaseModel):
    content: str | None = None
    tags: str | None = None


# ── GET /api/notes ──────────────────────────────────────────────

@router.get("/api/notes")
async def api_notes(
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
    type: str = Query(None),
    tag: str = Query(None),
    q: str = Query(None),
    date: str = Query(None),
):
    """JSON API for notes list with pagination, filtering, and search."""
    notes, total = await _query_notes(page, size, type, tag, q, date)
    has_more = page * size < total
    return {"notes": notes, "total": total, "page": page, "size": size, "has_more": has_more}


# ── GET /api/notes/{id} ────────────────────────────────────────

@router.get("/api/notes/{note_id}")
async def api_get_note(note_id: int):
    """Single note detail with attachments."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM notes WHERE id = ? AND is_deleted = 0", (note_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return JSONResponse({"error": "Note not found"}, status_code=404)

        note = dict(row)
        cursor = await db.execute(
            "SELECT * FROM attachments WHERE note_id = ? ORDER BY sort_order",
            (note_id,),
        )
        note["attachments"] = [dict(a) for a in await cursor.fetchall()]
        return note
    finally:
        await db.close()


# ── POST /api/notes ─────────────────────────────────────────────

@router.post("/api/notes", status_code=201)
async def api_create_note(body: CreateNoteRequest):
    """Create a new text note."""
    cfg = get_config()
    tz = get_timezone()
    now = datetime.now(tz)

    # Compute display_date using day_boundary_hour
    from braindump.database import _compute_display_date
    display_date = _compute_display_date(now, cfg.general.day_boundary_hour)

    # Generate file path
    date_dir = cfg.media_dir / "text" / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    random_hex = os.urandom(4).hex()
    filename = f"{now.strftime('%Y%m%d_%H%M%S')}_web{random_hex}.md"
    filepath = date_dir / filename
    filepath.write_text(body.content, encoding="utf-8")

    rel_path = str(filepath.relative_to(cfg.data_dir))

    db = await get_db()
    try:
        cursor = await db.execute(
            """INSERT INTO notes
               (content, media_type, file_path, file_size,
                created_at, display_date, imported_at,
                source, source_id, transcribe_status, tags)
               VALUES (?, 'text', ?, ?, ?, ?, ?, 'web', ?, 'not_needed', ?)""",
            (
                body.content, rel_path, len(body.content.encode("utf-8")),
                now.isoformat(), display_date, now.isoformat(),
                f"web_{random_hex}", body.tags,
            ),
        )
        await db.commit()
        note_id = cursor.lastrowid

        # Fetch and return the created note
        cursor = await db.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
        note = dict(await cursor.fetchone())
        note["attachments"] = []
        return note
    finally:
        await db.close()


# ── PUT /api/notes/{id} ─────────────────────────────────────────

@router.put("/api/notes/{note_id}")
async def api_update_note(note_id: int, body: UpdateNoteRequest):
    """Update note content and/or tags."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM notes WHERE id = ? AND is_deleted = 0", (note_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return JSONResponse({"error": "Note not found"}, status_code=404)

        note = dict(row)
        updates = []
        params = []

        if body.content is not None:
            updates.append("content = ?")
            params.append(body.content)
            # Update .md file for text notes
            if note["media_type"] == "text" and note["file_path"]:
                cfg = get_config()
                filepath = cfg.data_dir / note["file_path"]
                if filepath.exists():
                    filepath.write_text(body.content, encoding="utf-8")
                    updates.append("file_size = ?")
                    params.append(len(body.content.encode("utf-8")))

        if body.tags is not None:
            updates.append("tags = ?")
            params.append(body.tags)

        if updates:
            params.append(note_id)
            await db.execute(
                f"UPDATE notes SET {', '.join(updates)} WHERE id = ?", params
            )
            await db.commit()

        # Return updated note
        cursor = await db.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
        updated = dict(await cursor.fetchone())
        cursor = await db.execute(
            "SELECT * FROM attachments WHERE note_id = ? ORDER BY sort_order",
            (note_id,),
        )
        updated["attachments"] = [dict(a) for a in await cursor.fetchall()]
        return updated
    finally:
        await db.close()


# ── DELETE /api/notes/{id} ───────────────────────────────────────

@router.delete("/api/notes/{note_id}")
async def api_delete_note(note_id: int):
    """Soft delete a note."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE notes SET is_deleted = 1 WHERE id = ? AND is_deleted = 0", (note_id,)
        )
        await db.commit()
        if cursor.rowcount == 0:
            return JSONResponse({"error": "Note not found"}, status_code=404)
        return {"ok": True}
    finally:
        await db.close()


# ── POST /api/notes/{id}/restore ─────────────────────────────────

@router.post("/api/notes/{note_id}/restore")
async def api_restore_note(note_id: int):
    """Restore a soft-deleted note."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "UPDATE notes SET is_deleted = 0 WHERE id = ? AND is_deleted = 1", (note_id,)
        )
        await db.commit()
        if cursor.rowcount == 0:
            return JSONResponse({"error": "Note not found"}, status_code=404)
        return {"ok": True}
    finally:
        await db.close()


# ── GET /api/stats ───────────────────────────────────────────────

@router.get("/api/stats")
async def api_stats():
    """Statistics for the dashboard."""
    db = await get_db()
    try:
        # Total notes
        cursor = await db.execute("SELECT COUNT(*) FROM notes WHERE is_deleted = 0")
        total = (await cursor.fetchone())[0]

        # This month
        tz = get_timezone()
        now = datetime.now(tz)
        month_start = now.strftime("%Y-%m-01")
        cursor = await db.execute(
            "SELECT COUNT(*) FROM notes WHERE is_deleted = 0 AND display_date >= ?",
            (month_start,),
        )
        total_this_month = (await cursor.fetchone())[0]

        # Most active day
        cursor = await db.execute(
            """SELECT display_date, COUNT(*) as cnt FROM notes
               WHERE is_deleted = 0 GROUP BY display_date ORDER BY cnt DESC LIMIT 1"""
        )
        row = await cursor.fetchone()
        most_active_day = {"date": row[0], "count": row[1]} if row else {"date": "", "count": 0}

        # By type
        cursor = await db.execute(
            "SELECT media_type, COUNT(*) FROM notes WHERE is_deleted = 0 GROUP BY media_type"
        )
        by_type = {r[0]: r[1] for r in await cursor.fetchall()}

        # By source
        cursor = await db.execute(
            "SELECT source, COUNT(*) FROM notes WHERE is_deleted = 0 GROUP BY source"
        )
        by_source = {r[0]: r[1] for r in await cursor.fetchall()}

        # By month (last 12 months)
        cursor = await db.execute(
            """SELECT strftime('%Y-%m', display_date) as month, COUNT(*) as cnt
               FROM notes WHERE is_deleted = 0
               GROUP BY month ORDER BY month DESC LIMIT 12"""
        )
        by_month = [{"month": r[0], "count": r[1]} for r in await cursor.fetchall()]

        # Top tags
        cursor = await db.execute(
            "SELECT tags FROM notes WHERE is_deleted = 0 AND tags != ''"
        )
        tag_counts: dict[str, int] = {}
        for r in await cursor.fetchall():
            for t in r[0].split(","):
                t = t.strip()
                if t:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        top_tags = sorted(
            [{"tag": k, "count": v} for k, v in tag_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )[:30]

        unique_tags = len(tag_counts)

        return {
            "total": total,
            "total_this_month": total_this_month,
            "most_active_day": most_active_day,
            "unique_tags": unique_tags,
            "by_type": by_type,
            "by_source": by_source,
            "by_month": by_month,
            "top_tags": top_tags,
        }
    finally:
        await db.close()


# ── GET /api/calendar ────────────────────────────────────────────

@router.get("/api/calendar")
async def api_calendar(year: int = Query(...), month: int = Query(..., ge=1, le=12)):
    """Per-day note counts for a given month."""
    db = await get_db()
    try:
        month_prefix = f"{year:04d}-{month:02d}"
        cursor = await db.execute(
            """SELECT display_date, COUNT(*) as cnt FROM notes
               WHERE is_deleted = 0 AND display_date LIKE ?
               GROUP BY display_date""",
            (f"{month_prefix}%",),
        )
        days = {r[0]: r[1] for r in await cursor.fetchall()}
        return {"year": year, "month": month, "days": days}
    finally:
        await db.close()


# ── GET /api/tags ────────────────────────────────────────────────

@router.get("/api/tags")
async def api_tags():
    """All tags with counts, sorted by count descending."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT tags FROM notes WHERE is_deleted = 0 AND tags != ''"
        )
        tag_counts: dict[str, int] = {}
        for r in await cursor.fetchall():
            for t in r[0].split(","):
                t = t.strip()
                if t:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        tags = sorted(
            [{"tag": k, "count": v} for k, v in tag_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )
        return {"tags": tags}
    finally:
        await db.close()


# ── Internal helpers ─────────────────────────────────────────────

async def _query_notes(
    page: int, size: int,
    media_type: str | None,
    tag: str | None,
    q: str | None,
    date: str | None = None,
) -> tuple[list[dict], int]:
    """Query notes with filters. Returns (notes, total_count)."""
    db = await get_db()
    try:
        conditions = ["n.is_deleted = 0"]
        params: list = []

        if media_type:
            conditions.append("n.media_type = ?")
            params.append(media_type)

        if tag:
            conditions.append(
                "(n.tags LIKE ? OR n.tags LIKE ? OR n.tags = ? OR n.tags LIKE ?)"
            )
            params.extend([f"{tag},%", f"%,{tag},%", tag, f"%,{tag}"])

        if q:
            sanitized_q = _sanitize_fts_query(q)
            if sanitized_q:
                conditions.append(
                    "n.id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)"
                )
                params.append(sanitized_q)

        if date:
            conditions.append("n.display_date = ?")
            params.append(date)

        where = " AND ".join(conditions)

        try:
            cursor = await db.execute(
                f"SELECT COUNT(*) FROM notes n WHERE {where}", params
            )
            total = (await cursor.fetchone())[0]

            offset = (page - 1) * size
            cursor = await db.execute(
                f"""SELECT n.* FROM notes n
                    WHERE {where}
                    ORDER BY n.created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [size, offset],
            )
            rows = await cursor.fetchall()
        except sqlite3.OperationalError:
            return [], 0

        notes = []
        for row in rows:
            note = dict(row)
            cursor2 = await db.execute(
                "SELECT * FROM attachments WHERE note_id = ? ORDER BY sort_order",
                (note["id"],),
            )
            note["attachments"] = [dict(a) for a in await cursor2.fetchall()]
            notes.append(note)

        return notes, total
    finally:
        await db.close()
