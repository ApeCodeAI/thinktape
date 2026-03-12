"""Database operations and migrations."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from braindump.config import get_config

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
