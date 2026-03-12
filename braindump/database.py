"""Database operations and migrations."""

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from braindump.config import get_config, get_timezone

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
            print(f"  Applied migration: {mf.name}")


async def run_migrations():
    """CLI entry point for migrations."""
    cfg = get_config()
    print(f"Database: {cfg.db_path}")
    await init_db()
    print("Migrations complete.")


async def show_stats():
    """Show database statistics."""
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

        print(f"\nTotal notes: {total}")
        print("\nBy type:")
        for row in by_type:
            print(f"  {row[0]}: {row[1]}")
        print("\nBy source:")
        for row in by_source:
            print(f"  {row[0]}: {row[1]}")
    finally:
        await db.close()


# Filename pattern: YYYYMMDD_HHmmss_{source}{id}.{ext}
# Source prefixes are always 2 chars: tg, fl, mm, im
_FILENAME_RE = re.compile(
    r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_(tg|fl|mm|im)(.+)\..+$"
)

# Source prefix mapping
_SOURCE_MAP = {"tg": "telegram", "fl": "flomo", "mm": "memos", "im": "manual"}


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


async def rebuild_index():
    """Rebuild database from filesystem. Scans media/ and transcripts/ directories."""
    cfg = get_config()
    cfg.ensure_dirs()

    # Backup existing database before deleting
    backup_path = None
    if cfg.db_path.exists():
        timestamp = datetime.now(get_timezone()).strftime("%Y%m%d_%H%M%S")
        backup_path = cfg.backup_dir / f"braindump_{timestamp}.db"
        import shutil
        shutil.copy2(cfg.db_path, backup_path)
        print(f"Backed up database to: {backup_path}")
        cfg.db_path.unlink()
        print(f"Removed old database: {cfg.db_path}")

    try:
        await init_db()
        db = await get_db()
    except Exception:
        # Restore from backup if init fails
        if backup_path and backup_path.exists():
            import shutil
            shutil.copy2(backup_path, cfg.db_path)
            print(f"Restored database from backup: {backup_path}")
        raise

    now = datetime.now(get_timezone()).isoformat()
    count = 0
    media_types = ["text", "image", "video", "audio"]
    rebuild_ok = False

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
                    print(f"  Warning: cannot parse filename: {filepath.name}")
                    continue

                created_at = parsed["created_at"]
                source = parsed["source"]
                source_id = parsed["source_id"]
                display_date = _compute_display_date(created_at, cfg.general.day_boundary_hour)

                # Compute relative path
                rel_path = str(filepath.relative_to(cfg.data_dir))

                # Read content for text notes
                content = None
                if media_type == "text":
                    content = filepath.read_text(encoding="utf-8")

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

                cursor = await db.execute(
                    """INSERT INTO notes
                       (content, media_type, file_path, file_size,
                        created_at, display_date, imported_at,
                        source, source_id, transcript, transcribe_status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (content, media_type, rel_path, file_size,
                     created_at.isoformat(), display_date, now,
                     source, source_id, transcript, transcribe_status),
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
        rebuild_ok = True
        print(f"\nRebuild complete: {count} notes indexed from filesystem.")

    finally:
        await db.close()
        if not rebuild_ok and backup_path and backup_path.exists():
            import shutil
            shutil.copy2(backup_path, cfg.db_path)
            print(f"Rebuild failed — restored database from backup: {backup_path}")
