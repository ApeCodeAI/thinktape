"""Web routes — pages and API endpoints."""

import re
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from braindump.config import get_config, get_timezone
from braindump.database import get_db

# FTS5 special characters that need escaping
_FTS_SPECIAL = re.compile(r'["\*\(\)\-\^]')


def _sanitize_fts_query(q: str) -> str:
    """Escape special FTS5 characters and wrap each token in double quotes."""
    q = q.strip()
    if not q:
        return q
    # Remove characters that break FTS syntax
    q = _FTS_SPECIAL.sub(" ", q)
    # Wrap remaining tokens in double quotes for literal matching
    tokens = q.split()
    return " ".join(f'"{t}"' for t in tokens if t)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def timeline_page(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
    type: str = Query(None, alias="type"),
    tag: str = Query(None),
    q: str = Query(None),
):
    """Timeline page — main browsing view."""
    notes, total, tags_list = await _query_notes(page, size, type, tag, q)

    # Group notes by display_date
    grouped: dict[str, list] = {}
    for note in notes:
        date = note["display_date"]
        if date not in grouped:
            grouped[date] = []
        grouped[date].append(note)

    total_pages = (total + size - 1) // size

    return templates.TemplateResponse("timeline.html", {
        "request": request,
        "grouped_notes": grouped,
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
        "current_type": type,
        "current_tag": tag,
        "current_q": q or "",
        "all_tags": tags_list,
    })


@router.get("/note/{note_id}", response_class=HTMLResponse)
async def note_detail_page(request: Request, note_id: int):
    """Single note detail page."""
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM notes WHERE id = ? AND is_deleted = 0", (note_id,))
        row = await cursor.fetchone()
        if not row:
            return HTMLResponse("<h1>Not found</h1>", status_code=404)

        note = dict(row)

        # Get attachments
        cursor = await db.execute(
            "SELECT * FROM attachments WHERE note_id = ? ORDER BY sort_order",
            (note_id,),
        )
        attachments = [dict(r) for r in await cursor.fetchall()]
        note["attachments"] = attachments

        return templates.TemplateResponse("note.html", {
            "request": request,
            "note": note,
        })
    finally:
        await db.close()


@router.get("/api/notes")
async def api_notes(
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=100),
    type: str = Query(None),
    tag: str = Query(None),
    q: str = Query(None),
):
    """JSON API for notes list."""
    notes, total, _ = await _query_notes(page, size, type, tag, q)
    return {"notes": notes, "total": total, "page": page, "size": size}


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


async def _query_notes(
    page: int, size: int,
    media_type: str | None,
    tag: str | None,
    q: str | None,
) -> tuple[list[dict], int, list[str]]:
    """Query notes with filters. Returns (notes, total_count, all_tags)."""
    db = await get_db()
    try:
        conditions = ["n.is_deleted = 0"]
        params: list = []

        if media_type:
            conditions.append("n.media_type = ?")
            params.append(media_type)

        if tag:
            conditions.append("(n.tags LIKE ? OR n.tags LIKE ? OR n.tags = ?)")
            params.extend([f"{tag},%", f"%,{tag},%", tag])
            # Also match tag at end
            conditions[-1] = "(n.tags LIKE ? OR n.tags LIKE ? OR n.tags = ? OR n.tags LIKE ?)"
            params.append(f"%,{tag}")

        if q:
            sanitized_q = _sanitize_fts_query(q)
            if sanitized_q:
                conditions.append("n.id IN (SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?)")
                params.append(sanitized_q)

        where = " AND ".join(conditions)

        try:
            # Count
            cursor = await db.execute(f"SELECT COUNT(*) FROM notes n WHERE {where}", params)
            total = (await cursor.fetchone())[0]

            # Get notes with pagination
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
            # Invalid FTS query syntax — return empty results
            return [], 0, []

        notes = []
        for row in rows:
            note = dict(row)
            # Get attachment count
            cursor2 = await db.execute(
                "SELECT * FROM attachments WHERE note_id = ? ORDER BY sort_order",
                (note["id"],),
            )
            note["attachments"] = [dict(a) for a in await cursor2.fetchall()]
            notes.append(note)

        # Get all unique tags for filter dropdown
        cursor = await db.execute(
            "SELECT DISTINCT tags FROM notes WHERE is_deleted = 0 AND tags != ''"
        )
        tag_rows = await cursor.fetchall()
        all_tags = set()
        for r in tag_rows:
            for t in r[0].split(","):
                t = t.strip()
                if t:
                    all_tags.add(t)
        tags_list = sorted(all_tags)

        return notes, total, tags_list
    finally:
        await db.close()
