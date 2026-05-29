"""Database operations and migrations."""

import logging
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from braindump.config import get_config, get_timezone

logger = logging.getLogger("braindump.database")

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


def get_db_path() -> Path:
    return get_config().db_path


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(get_db_path())
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db


async def init_db():
    """Initialize database and run pending migrations."""
    db = await get_db()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id   INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        await db.commit()
        await _run_migrations(db)
    finally:
        await db.close()


async def _run_migrations(db: aiosqlite.Connection):
    """Run all pending SQL migration files."""
    if not MIGRATIONS_DIR.exists():
        return

    # Get already applied migrations
    cursor = await db.execute("SELECT name FROM migrations")
    applied = {row[0] for row in await cursor.fetchall()}

    # Find and sort migration files
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))

    for mf in migration_files:
        if mf.name in applied:
            continue

        sql = mf.read_text(encoding="utf-8")
        # Extract the "up" part (before "-- down")
        up_sql = sql.split("-- down")[0].replace("-- up", "").strip()

        if up_sql:
            await db.executescript(up_sql)

            # Record migration
            migration_id = int(mf.name.split("_")[0])
            await db.execute(
                "INSERT INTO migrations (id, name, applied_at) VALUES (?, ?, ?)",
                (migration_id, mf.name, datetime.now(timezone.utc).isoformat()),
            )
            await db.commit()
            logger.info("Applied migration: %s", mf.name)


async def run_migrations():
    """CLI entry point for migrations."""
    cfg = get_config()
    logger.info("Database: %s", cfg.db_path)
    await init_db()
    logger.info("Migrations complete.")


async def show_stats():
    """Show database statistics."""
    stats = await get_stats()
    logger.info("Total notes: %d", stats["total"])
    logger.info("By type:")
    for media_type, count in stats["by_type"].items():
        logger.info("  %s: %d", media_type, count)
    logger.info("By source:")
    for source, count in stats["by_source"].items():
        logger.info("  %s: %d", source, count)


async def get_stats() -> dict:
    """Return database statistics as a JSON-serializable dictionary."""
    await init_db()
    db = await get_db()
    try:
        cursor = await db.execute("SELECT COUNT(*) FROM notes WHERE is_deleted = 0")
        total = (await cursor.fetchone())[0]

        cursor = await db.execute(
            "SELECT media_type, COUNT(*) FROM notes WHERE is_deleted = 0 GROUP BY media_type"
        )
        by_type = await cursor.fetchall()

        cursor = await db.execute(
            "SELECT source, COUNT(*) FROM notes WHERE is_deleted = 0 GROUP BY source"
        )
        by_source = await cursor.fetchall()

        return {
            "ok": True,
            "total": total,
            "by_type": {row[0]: row[1] for row in by_type},
            "by_source": {row[0]: row[1] for row in by_source},
        }
    finally:
        await db.close()


# Filename pattern: YYYYMMDD_HHmmss_{source}{id}.{ext}
_FILENAME_RE = re.compile(
    r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(tg|fl|mm|im|web|cli)(.+)\..+$"
)

# Source prefix mapping
_SOURCE_MAP = {
    "tg": "telegram",
    "fl": "flomo",
    "mm": "memos",
    "im": "manual",
    "web": "web",
    "cli": "cli",
}


def _parse_media_filename(name: str) -> dict | None:
    """Parse a media filename into components. Returns None if not parseable."""
    m = _FILENAME_RE.match(name)
    if not m:
        return None
    y, mo, d, h, mi, s, src_prefix, src_id = m.groups()
    try:
        created_at = datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), tzinfo=get_timezone())
    except ValueError:
        return None
    source = _SOURCE_MAP.get(src_prefix, src_prefix)
    return {
        "created_at": created_at,
        "source": source,
        "source_id": f"{src_prefix}{src_id.split('.')[0]}" if '.' in name else f"{src_prefix}{src_id}",
    }


def _compute_display_date(created_at: datetime, day_boundary_hour: int) -> str:
    if created_at.hour < day_boundary_hour:
        d = created_at.date() - timedelta(days=1)
    else:
        d = created_at.date()
    return d.isoformat()


async def _init_db_at(db_path: Path):
    """Initialize a database at a specific path (used by rebuild_index)."""
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id   INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
        """)
        await db.commit()
        await _run_migrations(db)
    finally:
        await db.close()


async def rebuild_index():
    """Rebuild database from filesystem. Scans media/ and transcripts/ directories.

    Builds into a temporary database file first, then atomically replaces the
    original to avoid data loss if the rebuild fails mid-way.
    """
    cfg = get_config()
    cfg.ensure_dirs()

    # Build into a temp file in the same directory (same filesystem for atomic rename)
    tmp_db_path = cfg.db_path.with_suffix(".db.tmp")

    # Clean up any leftover temp file from a previous failed run
    if tmp_db_path.exists():
        tmp_db_path.unlink()

    try:
        await _init_db_at(tmp_db_path)
        db = await aiosqlite.connect(tmp_db_path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA foreign_keys=ON")
    except Exception:
        if tmp_db_path.exists():
            tmp_db_path.unlink()
        raise

    now = datetime.now(get_timezone()).isoformat()
    count = 0
    media_types = ["text", "image", "video", "audio"]

    try:
        for media_type in media_types:
            type_dir = cfg.media_dir / media_type
            if not type_dir.exists():
                continue

            for filepath in sorted(type_dir.rglob("*")):
                if not filepath.is_file():
                    continue

                parsed = _parse_media_filename(filepath.name)
                if not parsed:
                    logger.warning("Cannot parse filename: %s", filepath.name)
                    continue

                created_at = parsed["created_at"]
                source = parsed["source"]
                source_id = parsed["source_id"]
                display_date = _compute_display_date(created_at, cfg.general.day_boundary_hour)

                # Compute relative path
                rel_path = str(filepath.relative_to(cfg.data_dir))

                # Read content for text notes (parse frontmatter if present)
                content = None
                fm_meta = {}
                if media_type == "text":
                    from braindump.frontmatter import parse_frontmatter
                    raw_text = filepath.read_text(encoding="utf-8")
                    fm_meta, content = parse_frontmatter(raw_text)
                    if not fm_meta:
                        # No frontmatter — use full text as content
                        content = raw_text

                # Check for transcript
                transcript = None
                transcript_base = filepath.stem
                transcript_dir = cfg.transcripts_dir / created_at.strftime("%Y") / created_at.strftime("%m") / created_at.strftime("%d")
                txt_transcript = transcript_dir / f"{transcript_base}.txt"
                if txt_transcript.exists():
                    transcript = txt_transcript.read_text(encoding="utf-8")

                file_size = filepath.stat().st_size

                # Determine transcribe status
                if media_type in ("video", "audio"):
                    transcribe_status = "done" if transcript else "pending"
                else:
                    transcribe_status = "not_needed"

                # Extract AI fields from frontmatter if present
                import json as _json
                ai_title = fm_meta.get("title") if fm_meta else None
                ai_summary = fm_meta.get("summary") if fm_meta else None
                ai_mood = fm_meta.get("mood") if fm_meta else None
                ai_tags = None
                fm_tags_list = fm_meta.get("tags", []) if fm_meta else []
                if ai_title and isinstance(fm_tags_list, list) and fm_tags_list:
                    ai_tags = _json.dumps(fm_tags_list, ensure_ascii=False)

                # Determine summarize_status based on available AI data
                if ai_title:
                    summarize_status = "done"
                elif media_type == "text" and content and len(content) >= cfg.llm.min_content_length:
                    summarize_status = "skipped"
                else:
                    summarize_status = "skipped"

                # Extract user tags: from frontmatter or content #hashtags
                tags_str = ""
                if fm_tags_list and isinstance(fm_tags_list, list):
                    tags_str = ",".join(str(t) for t in fm_tags_list)

                cursor = await db.execute(
                    """INSERT INTO notes
                       (content, media_type, file_path, file_size,
                        created_at, display_date, imported_at,
                        source, source_id, transcript, transcribe_status,
                        tags, ai_title, ai_summary, ai_tags, ai_mood, summarize_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (content, media_type, rel_path, file_size,
                     created_at.isoformat(), display_date, now,
                     source, source_id, transcript, transcribe_status,
                     tags_str, ai_title, ai_summary, ai_tags, ai_mood, summarize_status),
                )
                note_id = cursor.lastrowid

                # Create attachment for non-text types
                if media_type != "text":
                    await db.execute(
                        "INSERT INTO attachments (note_id, file_path, media_type, file_size) VALUES (?, ?, ?, ?)",
                        (note_id, rel_path, media_type, file_size),
                    )

                count += 1

        await db.commit()
        logger.info("Rebuild complete: %d notes indexed from filesystem.", count)

    except Exception:
        await db.close()
        if tmp_db_path.exists():
            tmp_db_path.unlink()
        raise

    await db.close()

    # Also remove WAL/SHM files for the temp db before renaming
    for suffix in (".db.tmp-wal", ".db.tmp-shm"):
        wal_path = cfg.db_path.with_suffix(suffix)
        if wal_path.exists():
            wal_path.unlink()

    # Backup existing database, then atomically replace
    if cfg.db_path.exists():
        timestamp = datetime.now(get_timezone()).strftime("%Y%m%d_%H%M%S")
        backup_path = cfg.backup_dir / f"braindump_{timestamp}.db"
        import shutil
        shutil.copy2(cfg.db_path, backup_path)
        logger.info("Backed up old database to: %s", backup_path)

    os.replace(tmp_db_path, cfg.db_path)
    logger.info("Replaced database with rebuilt index.")
