"""Tests for the explicit, read-only legacy item migration."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml
import pytest
from click.testing import CliRunner

from thinktape.cli import cli
from thinktape.config import Config
from thinktape.core import MigrationRequiredError, ThinkTape
from thinktape.models import Asset, Item


def _write_legacy_item(data_dir: Path, item_id: str) -> Path:
    item_dir = data_dir / "items" / item_id
    (item_dir / "images").mkdir(parents=True)
    metadata = {
        "id": item_id,
        "created_at": "2025-01-02T03:04:05+08:00",
        "updated_at": "2025-02-03T04:05:06+08:00",
        "type": "note",
        "source": "cli",
        "tags": ["legacy"],
        "status": "archived",
        "bookmark_url": None,
        "summary": "preserved summary",
        "telegram_message_id": 42,
        "has_audio": True,
        "has_images": True,
        "has_video": True,
    }
    (item_dir / "item.yaml").write_text(
        yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False), encoding="utf-8",
    )
    (item_dir / "content.md").write_text("legacy body #inline\n", encoding="utf-8")
    (item_dir / "audio.ogg").write_bytes(b"legacy-audio")
    (item_dir / "video.mp4").write_bytes(b"legacy-video")
    (item_dir / "images" / "001.jpg").write_bytes(b"legacy-image")
    return item_dir


def _snapshot_tree(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _matching_legacy_db_item(item_id: str) -> Item:
    return Item(
        id=item_id,
        created_at=datetime.fromisoformat("2025-01-02T03:04:05+08:00"),
        updated_at=datetime.fromisoformat("2025-02-03T04:05:06+08:00"),
        type="note",
        source="cli",
        tags=["legacy"],
        status="archived",
        summary="preserved summary",
        telegram_message_id=42,
        has_audio=True,
        has_images=True,
        has_video=True,
        content="legacy body #inline\n",
    )


async def test_legacy_migration_dry_run_apply_idempotent_and_read_only(tmp_path: Path):
    item_id = "20250102-030405-abcd"
    legacy_dir = _write_legacy_item(tmp_path, item_id)
    before = _snapshot_tree(tmp_path / "items")
    brain = ThinkTape(Config(data_dir=tmp_path))
    try:
        dry_run = await brain.migrate_legacy(dry_run=True)
        assert dry_run["mode"] == "dry-run"
        assert dry_run["counts"] == {
            "scanned": 1,
            "ready": 1,
            "imported": 0,
            "updated": 0,
            "skipped": 0,
            "assets_found": 3,
            "assets_imported": 0,
            "verified_files": 5,
            "issues": 0,
        }
        assert dry_run["issues"] == []
        assert dry_run["items"][0]["action"] == "would-import"
        assert dry_run["items"][0]["checksums"]["metadata"] == hashlib.sha256(
            (legacy_dir / "item.yaml").read_bytes()
        ).hexdigest()
        assert not brain.config.db_path.exists()
        assert not tmp_path.joinpath("assets").exists()
        assert _snapshot_tree(tmp_path / "items") == before

        applied = await brain.migrate_legacy(dry_run=False)
        assert applied["mode"] == "apply"
        assert applied["counts"]["imported"] == 1
        assert applied["counts"]["assets_imported"] == 3
        assert applied["counts"]["issues"] == 0

        await brain.connect()
        item = await brain.get(item_id)
        assert item is not None
        assert item.id == item_id
        assert item.created_at == datetime.fromisoformat("2025-01-02T03:04:05+08:00")
        assert item.updated_at == datetime.fromisoformat("2025-02-03T04:05:06+08:00")
        assert item.content == "legacy body #inline\n"
        assert item.tags == ["legacy"]
        assert item.status == "archived"
        assert item.summary == "preserved summary"
        assert item.telegram_message_id == 42
        assert item.images == ["001.jpg"]
        assets = await brain.list_assets(item_id)
        assert {a.kind for a in assets} == {"audio", "image", "video"}
        for asset in assets:
            destination = brain.asset_store.path_for(asset)
            assert hashlib.sha256(destination.read_bytes()).hexdigest() == asset.sha256
        assert _snapshot_tree(tmp_path / "items") == before

        repeated = await brain.migrate_legacy(dry_run=False)
        assert repeated["counts"]["imported"] == 0
        assert repeated["counts"]["updated"] == 0
        assert repeated["counts"]["skipped"] == 1
        assert repeated["counts"]["assets_imported"] == 0
        assert repeated["counts"]["issues"] == 0
        assert _snapshot_tree(tmp_path / "items") == before
    finally:
        await brain.close()


async def test_legacy_migration_reports_invalid_item_without_partial_write(tmp_path: Path):
    item_id = "20250102-030405-bad0"
    item_dir = tmp_path / "items" / item_id
    item_dir.mkdir(parents=True)
    (item_dir / "item.yaml").write_text("id: different-id\n", encoding="utf-8")
    (item_dir / "content.md").write_text("must not import", encoding="utf-8")
    before = _snapshot_tree(tmp_path / "items")

    brain = ThinkTape(Config(data_dir=tmp_path))
    report = await brain.migrate_legacy(dry_run=False)
    assert report["counts"]["imported"] == 0
    assert report["counts"]["issues"] == 1
    assert report["issues"][0]["code"] == "item_id_mismatch"
    db = sqlite3.connect(brain.config.db_path)
    assert db.execute("SELECT COUNT(*) FROM items").fetchone() == (0,)
    db.close()
    assert _snapshot_tree(tmp_path / "items") == before


async def test_migration_never_overwrites_conflicting_canonical_item(tmp_path: Path):
    item_id = "20250102-030405-a11a"
    canonical_created_at = datetime.fromisoformat("2024-01-01T00:00:00+08:00")
    brain = ThinkTape(Config(data_dir=tmp_path))
    await brain.connect()
    try:
        await brain.index.upsert(Item(
            id=item_id,
            created_at=canonical_created_at,
            updated_at=canonical_created_at,
            type="thought",
            source="api",
            content="canonical must win",
        ))
        _write_legacy_item(tmp_path, item_id)

        first = await brain.migrate_legacy(dry_run=False)
        second = await brain.migrate_legacy(dry_run=False)

        assert first["counts"]["updated"] == 0
        assert first["issues"][0]["code"] == "item_conflict"
        assert second["issues"][0]["code"] == "item_conflict"
        stored = await brain.get(item_id)
        assert stored is not None
        assert stored.content == "canonical must win"
        assert stored.created_at == canonical_created_at
        assert await brain.list_assets(item_id) == []
    finally:
        await brain.close()


async def test_old_db_derived_tag_union_matches_legacy_without_updating_item(
    tmp_path: Path,
):
    item_id = "20250102-030405-a55d"
    brain = ThinkTape(Config(data_dir=tmp_path))
    await brain.connect()
    try:
        await brain.index.upsert(Item(
            id=item_id,
            created_at=datetime.fromisoformat("2025-01-02T03:04:05+08:00"),
            updated_at=datetime.fromisoformat("2025-02-03T04:05:06+08:00"),
            type="note",
            source="cli",
            tags=["legacy", "inline"],
            status="archived",
            summary="preserved summary",
            telegram_message_id=42,
            content="legacy body #inline\n",
        ))
        _write_legacy_item(tmp_path, item_id)
        await brain.index.db.execute(
            """
            CREATE TRIGGER reject_tag_normalization BEFORE UPDATE ON items
            BEGIN SELECT RAISE(FAIL, 'canonical item must not be updated'); END
            """
        )
        await brain.index.db.commit()

        report = await brain.migrate_legacy(dry_run=False)

        assert report["ok"] is True
        assert report["counts"]["assets_imported"] == 3
        stored = await brain.get(item_id)
        assert stored is not None
        assert stored.tags == ["legacy", "inline"]
        assert stored.content == "legacy body #inline\n"
    finally:
        await brain.close()


async def test_migration_does_not_ignore_unexplained_canonical_tags(tmp_path: Path):
    item_id = "20250102-030405-a55c"
    brain = ThinkTape(Config(data_dir=tmp_path))
    await brain.connect()
    try:
        await brain.index.upsert(Item(
            id=item_id,
            created_at=datetime.fromisoformat("2025-01-02T03:04:05+08:00"),
            updated_at=datetime.fromisoformat("2025-02-03T04:05:06+08:00"),
            type="note",
            source="cli",
            tags=["legacy", "inline", "canonical-only"],
            status="archived",
            summary="preserved summary",
            telegram_message_id=42,
            content="legacy body #inline\n",
        ))
        _write_legacy_item(tmp_path, item_id)

        report = await brain.migrate_legacy(dry_run=False)

        assert report["ok"] is False
        assert report["issues"][0]["code"] == "item_conflict"
        stored = await brain.get(item_id)
        assert stored is not None
        assert stored.tags == ["legacy", "inline", "canonical-only"]
        assert await brain.list_assets(item_id) == []
    finally:
        await brain.close()


async def test_identical_canonical_item_gains_assets_without_item_update(tmp_path: Path):
    item_id = "20250102-030405-a55e"
    brain = ThinkTape(Config(data_dir=tmp_path))
    await brain.connect()
    try:
        await brain.index.upsert(Item(
            id=item_id,
            created_at=datetime.fromisoformat("2025-01-02T03:04:05+08:00"),
            updated_at=datetime.fromisoformat("2025-02-03T04:05:06+08:00"),
            type="note",
            source="cli",
            tags=["legacy"],
            status="archived",
            summary="preserved summary",
            telegram_message_id=42,
            content="legacy body #inline\n",
        ))
        _write_legacy_item(tmp_path, item_id)
        await brain.index.db.execute(
            """
            CREATE TRIGGER reject_item_update BEFORE UPDATE ON items
            BEGIN SELECT RAISE(FAIL, 'canonical item must not be updated'); END
            """
        )
        await brain.index.db.commit()

        applied = await brain.migrate_legacy(dry_run=False)
        repeated = await brain.migrate_legacy(dry_run=False)

        assert applied["ok"] is True
        assert applied["counts"]["assets_imported"] == 3
        assert repeated["counts"]["skipped"] == 1
        assert len(await brain.list_assets(item_id)) == 3
    finally:
        await brain.close()


async def test_identical_item_can_gain_only_missing_matching_assets(tmp_path: Path):
    item_id = "20250102-030405-a55f"
    _write_legacy_item(tmp_path, item_id)
    config = Config(data_dir=tmp_path)
    first = await ThinkTape(config).migrate_legacy(dry_run=False)
    assert first["ok"] is True

    brain = ThinkTape(config)
    await brain.connect()
    try:
        assets = await brain.list_assets(item_id)
        keep = next(asset for asset in assets if asset.kind == "audio")
        for asset in assets:
            if asset.id != keep.id:
                brain.asset_store.path_for(asset).unlink()
        await brain.index.db.execute(
            "DELETE FROM assets WHERE item_id = ? AND id != ?", (item_id, keep.id)
        )
        await brain.index.db.commit()
        await brain.index.db.execute(
            """
            CREATE TRIGGER reject_partial_item_update BEFORE UPDATE ON items
            BEGIN SELECT RAISE(FAIL, 'canonical item must not be updated'); END
            """
        )
        await brain.index.db.commit()

        applied = await brain.migrate_legacy(dry_run=False)
        repeated = await brain.migrate_legacy(dry_run=False)

        assert applied["ok"] is True
        assert applied["counts"]["assets_imported"] == 2
        assert len(await brain.list_assets(item_id)) == 3
        assert repeated["counts"]["skipped"] == 1
    finally:
        await brain.close()


async def test_migration_reports_missing_legacy_content(tmp_path: Path):
    item_id = "20250102-030405-c017"
    item_dir = _write_legacy_item(tmp_path, item_id)
    (item_dir / "content.md").unlink()

    report = await ThinkTape(Config(data_dir=tmp_path)).migrate_legacy(dry_run=True)

    assert report["issues"][0]["code"] == "missing_legacy_content"
    assert not (tmp_path / "thinktape.db").exists()


async def test_migration_discovers_arbitrary_safe_media_extensions(tmp_path: Path):
    item_id = "20250102-030405-e710"
    item_dir = _write_legacy_item(tmp_path, item_id)
    (item_dir / "audio.ogg").rename(item_dir / "audio.weird-safe_1")
    (item_dir / "video.mp4").rename(item_dir / "video.unlisted_2")
    brain = ThinkTape(Config(data_dir=tmp_path))
    try:
        report = await brain.migrate_legacy(dry_run=False)
        assert report["ok"] is True
        await brain.connect()
        assets = await brain.list_assets(item_id)
        assert {asset.original_filename for asset in assets} >= {
            "audio.weird-safe_1", "video.unlisted_2",
        }
        assert {Path(asset.path).name for asset in assets} >= {
            "audio.weird-safe_1", "video.unlisted_2",
        }
    finally:
        await brain.close()


async def test_migration_reports_flagged_missing_and_ambiguous_media(tmp_path: Path):
    missing_id = "20250102-030405-1111"
    missing_dir = _write_legacy_item(tmp_path, missing_id)
    (missing_dir / "audio.ogg").unlink()
    ambiguous_id = "20250102-030405-2222"
    ambiguous_dir = _write_legacy_item(tmp_path, ambiguous_id)
    (ambiguous_dir / "audio.second-format").write_bytes(b"other-audio")

    brain = ThinkTape(Config(data_dir=tmp_path))
    report = await brain.migrate_legacy(dry_run=True)
    issues = {issue["item_id"]: issue["code"] for issue in report["issues"]}
    assert issues[missing_id] == "missing_expected_media"
    assert issues[ambiguous_id] == "ambiguous_legacy_media"
    assert not brain.config.db_path.exists()


async def test_migration_rejects_symlinked_legacy_inputs(tmp_path: Path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret outside content", encoding="utf-8")
    item_id = "20250102-030405-5a1e"
    item_dir = _write_legacy_item(tmp_path, item_id)
    (item_dir / "content.md").unlink()
    (item_dir / "content.md").symlink_to(outside)

    brain = ThinkTape(Config(data_dir=tmp_path))
    report = await brain.migrate_legacy(dry_run=False)
    assert report["issues"][0]["code"] == "unsafe_legacy_path"
    assert outside.read_text(encoding="utf-8") == "secret outside content"


async def test_migration_rejects_legacy_item_directory_symlink(tmp_path: Path):
    item_id = "20250102-030405-0a75"
    real_root = tmp_path / "outside-item"
    real_root.mkdir()
    real_dir = _write_legacy_item(real_root, item_id)
    items_dir = tmp_path / "items"
    items_dir.mkdir()
    (items_dir / item_id).symlink_to(real_dir, target_is_directory=True)

    brain = ThinkTape(Config(data_dir=tmp_path))
    report = await brain.migrate_legacy(dry_run=True)
    assert report["issues"][0]["code"] == "unsafe_legacy_path"
    assert not brain.config.db_path.exists()


def test_migrate_legacy_cli_outputs_structured_json(tmp_path: Path, monkeypatch):
    _write_legacy_item(tmp_path, "20250102-030405-cdef")
    monkeypatch.setenv("THINKTAPE_DATA_DIR", str(tmp_path))
    runner = CliRunner()

    result = runner.invoke(cli, ["migrate-legacy", "--dry-run"], catch_exceptions=False)
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["mode"] == "dry-run"
    assert report["counts"]["ready"] == 1
    assert report["counts"]["imported"] == 0

    result = runner.invoke(cli, ["migrate-legacy", "--apply"], catch_exceptions=False)
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["mode"] == "apply"
    assert report["counts"]["imported"] == 1


def test_migrate_legacy_cli_exits_nonzero_when_report_has_issues(tmp_path: Path, monkeypatch):
    item_id = "20250102-030405-bad2"
    item_dir = tmp_path / "items" / item_id
    item_dir.mkdir(parents=True)
    (item_dir / "item.yaml").write_text("id: wrong\n", encoding="utf-8")
    monkeypatch.setenv("THINKTAPE_DATA_DIR", str(tmp_path))

    result = CliRunner().invoke(cli, ["migrate-legacy", "--dry-run"])

    assert result.exit_code == 1
    assert json.loads(result.output)["ok"] is False


async def test_migration_cancellation_rolls_back_item_and_promoted_assets(
    tmp_path: Path, monkeypatch,
):
    item_id = "20250102-030405-ca11"
    _write_legacy_item(tmp_path, item_id)
    brain = ThinkTape(Config(data_dir=tmp_path))
    calls = 0

    from thinktape.migrate import LegacyMigrator

    real_verify = LegacyMigrator._verify_source_hashes

    async def cancel_during_apply(self, expected):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise asyncio.CancelledError
        await real_verify(self, expected)

    monkeypatch.setattr(LegacyMigrator, "_verify_source_hashes", cancel_during_apply)
    with pytest.raises(asyncio.CancelledError):
        await brain.migrate_legacy(dry_run=False)
    db = sqlite3.connect(brain.config.db_path)
    assert db.execute("SELECT COUNT(*) FROM items").fetchone() == (0,)
    db.close()
    assert not (tmp_path / "assets" / item_id).exists()


async def test_normal_startup_refuses_unmarked_database_without_mutation(tmp_path: Path):
    db_path = tmp_path / "thinktape.db"
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE items (id TEXT PRIMARY KEY)")
    db.commit()
    db.close()
    before = db_path.read_bytes()

    brain = ThinkTape(Config(data_dir=tmp_path))
    with pytest.raises(MigrationRequiredError, match="migrate-legacy"):
        await brain.connect()

    assert db_path.read_bytes() == before
    assert not (tmp_path / "assets").exists()


async def test_migration_dry_run_does_not_create_or_mutate_storage(tmp_path: Path):
    _write_legacy_item(tmp_path, "20250102-030405-d7a0")
    before = _snapshot_tree(tmp_path)

    report = await ThinkTape(Config(data_dir=tmp_path)).migrate_legacy(dry_run=True)

    assert report["ok"] is True
    assert report["items"][0]["action"] == "would-import"
    assert _snapshot_tree(tmp_path) == before
    assert not (tmp_path / "thinktape.db").exists()
    assert not (tmp_path / "assets").exists()


@pytest.mark.parametrize("legacy_count", [0, 1], ids=["empty-tree", "incomplete-tree"])
async def test_unmarked_old_db_requires_every_row_in_valid_legacy_tree(
    tmp_path: Path, legacy_count: int,
):
    config = Config(data_dir=tmp_path)
    item_ids = ["20250102-030405-b001", "20250102-030405-b002"]
    old = ThinkTape(config)
    await old.connect()
    for item_id in item_ids:
        await old.index.upsert(_matching_legacy_db_item(item_id))
    await old.close()
    for item_id in item_ids[:legacy_count]:
        _write_legacy_item(tmp_path, item_id)
    db = sqlite3.connect(config.db_path)
    db.execute("DELETE FROM storage_metadata WHERE key = 'storage_contract'")
    db.commit()
    db.close()

    report = await ThinkTape(config).migrate_legacy(dry_run=False)

    missing_ids = {
        issue["item_id"]
        for issue in report["issues"]
        if issue["code"] == "missing_legacy_item"
    }
    assert missing_ids == set(item_ids[legacy_count:])
    assert report["ok"] is False
    db = sqlite3.connect(config.db_path)
    marker = db.execute(
        "SELECT value FROM storage_metadata WHERE key = 'storage_contract'"
    ).fetchone()
    db.close()
    assert marker is None


async def test_unmarked_old_db_media_flags_must_match_legacy_asset_records(
    tmp_path: Path,
):
    config = Config(data_dir=tmp_path)
    item_id = "20250102-030405-b003"
    old = ThinkTape(config)
    await old.connect()
    stale = _matching_legacy_db_item(item_id)
    stale.has_audio = False
    await old.index.upsert(stale)
    await old.close()
    _write_legacy_item(tmp_path, item_id)
    db = sqlite3.connect(config.db_path)
    db.execute("DELETE FROM storage_metadata WHERE key = 'storage_contract'")
    db.commit()
    db.close()

    report = await ThinkTape(config).migrate_legacy(dry_run=False)

    assert report["ok"] is False
    assert report["issues"] == [{
        "item_id": item_id,
        "code": "media_flag_mismatch",
        "message": "pre-existing SQLite media flags do not match legacy asset records",
    }]
    db = sqlite3.connect(config.db_path)
    marker = db.execute(
        "SELECT value FROM storage_metadata WHERE key = 'storage_contract'"
    ).fetchone()
    asset_count = db.execute(
        "SELECT COUNT(*) FROM assets WHERE item_id = ?", (item_id,)
    ).fetchone()
    db.close()
    assert marker is None
    assert asset_count == (0,)


async def test_successful_apply_sets_marker_and_allows_normal_startup(tmp_path: Path):
    item_id = "20250102-030405-a991"
    _write_legacy_item(tmp_path, item_id)
    config = Config(data_dir=tmp_path)

    report = await ThinkTape(config).migrate_legacy(dry_run=False)
    assert report["ok"] is True

    db = sqlite3.connect(config.db_path)
    marker = db.execute(
        "SELECT value FROM storage_metadata WHERE key = 'storage_contract'"
    ).fetchone()
    db.close()
    assert marker == ("sqlite-db-first-v1",)

    restarted = ThinkTape(config)
    await restarted.connect()
    try:
        assert await restarted.get(item_id) is not None
    finally:
        await restarted.close()


async def test_apply_with_issues_leaves_database_unmarked(tmp_path: Path):
    item_id = "20250102-030405-bad1"
    item_dir = tmp_path / "items" / item_id
    item_dir.mkdir(parents=True)
    (item_dir / "item.yaml").write_text("id: different\n", encoding="utf-8")
    config = Config(data_dir=tmp_path)

    report = await ThinkTape(config).migrate_legacy(dry_run=False)
    assert report["ok"] is False

    db = sqlite3.connect(config.db_path)
    marker = db.execute(
        "SELECT value FROM storage_metadata WHERE key = 'storage_contract'"
    ).fetchone()
    db.close()
    assert marker is None
    with pytest.raises(MigrationRequiredError, match="migrate-legacy"):
        await ThinkTape(config).connect()


async def test_fresh_database_is_marked_db_first(tmp_path: Path):
    config = Config(data_dir=tmp_path)
    brain = ThinkTape(config)
    await brain.connect()
    await brain.close()

    db = sqlite3.connect(config.db_path)
    marker = db.execute(
        "SELECT value FROM storage_metadata WHERE key = 'storage_contract'"
    ).fetchone()
    db.close()
    assert marker == ("sqlite-db-first-v1",)
