"""DB-first storage behavior and regression tests."""
from __future__ import annotations

import asyncio
import hashlib
import stat
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from thinktape.config import Config
from thinktape.core import ThinkTape
from thinktape.models import Item


class FatalTestError(BaseException):
    pass


async def test_crud_is_db_only_when_legacy_files_are_absent(
    brain: ThinkTape, config: Config,
):
    item = await brain.add("database content", tags=["explicit"])

    # Normal writes must not create the retired YAML/Markdown item tree.
    assert not (config.items_dir / item.id).exists()
    shutil.rmtree(config.items_dir, ignore_errors=True)

    fetched = await brain.get(item.id)
    assert fetched is not None
    assert fetched.content == "database content"
    assert fetched.tags == ["explicit"]

    updated = await brain.update(item.id, content="updated in sqlite", tags=["db"])
    assert updated is not None
    assert updated.content == "updated in sqlite"
    assert updated.tags == ["db"]

    assert [it.id for it in await brain.list(tag="db")] == [item.id]
    assert [it.id for it in await brain.search("updated")] == [item.id]

    assert await brain.delete(item.id) is True
    deleted = await brain.get(item.id)
    assert deleted is not None
    assert deleted.status == "deleted"
    assert await brain.list() == []
    assert not config.items_dir.exists()


async def test_assets_are_copied_to_immutable_store_and_recorded(
    brain: ThinkTape, config: Config, tmp_path: Path,
):
    audio = tmp_path / "memo.m4a"
    image = tmp_path / "photo.jpg"
    video = tmp_path / "clip.mp4"
    audio.write_bytes(b"audio-bytes")
    image.write_bytes(b"image-bytes")
    video.write_bytes(b"video-bytes")

    item = await brain.add(
        "with media",
        audio_path=audio,
        image_paths=[image],
        video_path=video,
    )

    assets = await brain.list_assets(item.id)
    assert [asset.kind for asset in assets] == ["audio", "image", "video"]
    assert item.has_audio is True
    assert item.has_images is True
    assert item.has_video is True
    assert item.images == ["001.jpg"]

    expected = {
        "audio": (b"audio-bytes", "memo.m4a", "audio/"),
        "image": (b"image-bytes", "photo.jpg", "image/"),
        "video": (b"video-bytes", "clip.mp4", "video/"),
    }
    for asset in assets:
        payload, original_name, mime_prefix = expected[asset.kind]
        assert asset.path.startswith(f"assets/{item.id}/")
        assert asset.sha256 == hashlib.sha256(payload).hexdigest()
        assert asset.byte_size == len(payload)
        assert asset.original_filename == original_name
        assert asset.mime_type is not None and asset.mime_type.startswith(mime_prefix)
        path = config.data_dir / asset.path
        assert path.read_bytes() == payload
        assert path.is_file()
        assert stat.S_IMODE(path.stat().st_mode) == 0o444

    # The legacy item tree is not involved in normal media storage.
    assert not (config.items_dir / item.id).exists()


async def test_create_rolls_back_db_and_assets_when_copy_fails(
    brain: ThinkTape, config: Config, tmp_path: Path,
):
    good = tmp_path / "good.jpg"
    good.write_bytes(b"good")
    missing = tmp_path / "missing.jpg"

    with pytest.raises(FileNotFoundError):
        await brain.add("must roll back", image_paths=[good, missing])

    assert await brain.list(status=None) == []
    async with brain.index.db.execute("SELECT COUNT(*) AS n FROM assets") as cursor:
        assert (await cursor.fetchone())["n"] == 0
    assert not any(config.assets_dir.glob("*/")) if config.assets_dir.exists() else True


async def test_create_rolls_back_promoted_files_when_db_commit_fails(
    brain: ThinkTape, config: Config, tmp_path: Path, monkeypatch,
):
    audio = tmp_path / "memo.ogg"
    audio.write_bytes(b"immutable")

    async def fail_commit():
        raise RuntimeError("simulated commit failure")

    monkeypatch.setattr(brain.index.db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await brain.add("must roll back", audio_path=audio)

    async with brain.index.db.execute("SELECT COUNT(*) AS n FROM assets") as cursor:
        assert (await cursor.fetchone())["n"] == 0
    assert not any(config.assets_dir.glob("*/")) if config.assets_dir.exists() else True


async def test_create_removes_promoted_files_if_promotion_reports_failure(
    brain: ThinkTape, config: Config, tmp_path: Path, monkeypatch,
):
    audio = tmp_path / "memo.ogg"
    audio.write_bytes(b"immutable")
    original_promote = brain.asset_store.promote

    async def promote_then_fail(staged):
        await original_promote(staged)
        raise RuntimeError("simulated post-promote failure")

    monkeypatch.setattr(brain.asset_store, "promote", promote_then_fail)
    with pytest.raises(RuntimeError, match="post-promote failure"):
        await brain.add("must roll back", audio_path=audio)

    assert await brain.list(status=None) == []
    async with brain.index.db.execute("SELECT COUNT(*) AS n FROM assets") as cursor:
        assert (await cursor.fetchone())["n"] == 0
    assert not any(config.assets_dir.glob("*/")) if config.assets_dir.exists() else True


async def test_failed_promotion_preserves_preexisting_asset_directory(
    brain: ThinkTape, config: Config, tmp_path: Path, monkeypatch,
):
    item_id = "20250102-030405-cafe"
    sentinel_dir = config.assets_dir / item_id
    sentinel_dir.mkdir(parents=True)
    sentinel = sentinel_dir / "sentinel.txt"
    sentinel.write_bytes(b"pre-existing")
    audio = tmp_path / "memo.ogg"
    audio.write_bytes(b"new-audio")
    monkeypatch.setattr("thinktape.core.generate_id", lambda _now: item_id)

    with pytest.raises(FileExistsError):
        await brain.add("must not remove sentinel", audio_path=audio)

    assert sentinel.read_bytes() == b"pre-existing"
    assert await brain.get(item_id) is None
    staging = config.assets_dir / ".staging"
    assert not staging.exists() or not any(staging.iterdir())


async def test_db_and_asset_records_survive_restart(tmp_path: Path):
    config = Config(data_dir=tmp_path)
    image = tmp_path / "restart.png"
    image.write_bytes(b"restart-image")

    first = ThinkTape(config)
    await first.connect()
    created = await first.add(
        "persistent #derived", tags=["explicit"], image_paths=[image],
    )
    created_at = created.created_at
    await first.close()

    shutil.rmtree(config.items_dir, ignore_errors=True)
    restarted = ThinkTape(config)
    await restarted.connect()
    try:
        fetched = await restarted.get(created.id)
        assert fetched is not None
        assert fetched.created_at == created_at
        assert fetched.content == "persistent #derived"
        assert fetched.tags == ["explicit"]
        assert fetched.images == ["001.png"]
        asset = (await restarted.list_assets(created.id))[0]
        assert restarted.asset_store.path_for(asset).read_bytes() == b"restart-image"
        assert [item.id for item in await restarted.search("persistent")] == [created.id]
        assert (await restarted.search("persistent"))[0].tags == ["explicit", "derived"]
    finally:
        await restarted.close()


async def test_existing_sqlite_items_rebuild_derived_tags_on_restart(tmp_path: Path):
    config = Config(data_dir=tmp_path)
    db = sqlite3.connect(config.db_path)
    db.execute(
        """
        CREATE TABLE items (
            id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            type TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL,
            tags TEXT NOT NULL, bookmark_url TEXT, summary TEXT,
            has_audio INTEGER NOT NULL, has_images INTEGER NOT NULL,
            has_video INTEGER NOT NULL, telegram_message_id INTEGER, content TEXT NOT NULL
        )
        """
    )
    db.execute("CREATE TABLE storage_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    db.execute(
        "INSERT INTO storage_metadata VALUES ('storage_contract', 'sqlite-db-first-v1')"
    )
    db.execute(
        "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            "20250102-030405-cafe", "2025-01-02T03:04:05+08:00",
            "2025-01-02T03:04:05+08:00", "thought", "cli", "active",
            '["explicit"]', None, None, 0, 0, 0, None, "old db #derived",
        ),
    )
    db.commit()
    db.close()

    restarted = ThinkTape(config)
    await restarted.connect()
    try:
        assert [item.id for item in await restarted.list(tag="explicit")] == [
            "20250102-030405-cafe"
        ]
        assert [item.id for item in await restarted.list(tag="derived")] == [
            "20250102-030405-cafe"
        ]
        assert set(await restarted.all_tags()) == {"explicit", "derived"}
    finally:
        await restarted.close()


async def test_hard_delete_removes_db_rows_and_canonical_assets_only(
    brain: ThinkTape, config: Config, tmp_path: Path,
):
    audio = tmp_path / "delete.ogg"
    audio.write_bytes(b"delete-me")
    item = await brain.add("hard delete", audio_path=audio)
    legacy_dir = config.items_dir / item.id
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "content.md"
    legacy_file.write_text("legacy must survive", encoding="utf-8")

    assert await brain.hard_delete(item.id) is True
    assert await brain.get(item.id) is None
    assert await brain.list_assets(item.id) == []
    assert not (config.assets_dir / item.id).exists()
    assert legacy_file.read_text(encoding="utf-8") == "legacy must survive"


async def test_concurrent_adds_retry_id_collisions_without_overwriting(
    brain: ThinkTape, monkeypatch,
):
    collision_id = "20250102-030405-cafe"
    fallback_ids = iter((
        collision_id,
        collision_id,
        "20250102-030405-f001",
        "20250102-030405-f002",
    ))
    monkeypatch.setattr("thinktape.core.generate_id", lambda _now: next(fallback_ids))

    real_get = brain.index.get
    collision_reads = 0
    both_checked = asyncio.Event()

    async def synchronize_collision_check(item_id: str):
        nonlocal collision_reads
        if item_id == collision_id and not both_checked.is_set():
            collision_reads += 1
            if collision_reads == 2:
                both_checked.set()
            await asyncio.wait_for(both_checked.wait(), timeout=1)
        return await real_get(item_id)

    monkeypatch.setattr(brain.index, "get", synchronize_collision_check)

    first, second = await asyncio.gather(
        brain.add("first collision contender"),
        brain.add("second collision contender"),
    )

    assert first.id != second.id
    stored = await brain.list(status=None)
    assert {item.id: item.content for item in stored} == {
        first.id: "first collision contender",
        second.id: "second collision contender",
    }


async def test_concurrent_updates_serialize_read_modify_write_without_lost_fields(
    brain: ThinkTape, monkeypatch,
):
    item = await brain.add("original", tags=["old"])
    real_upsert = brain.index.upsert
    writers_waiting = 0
    both_read = asyncio.Event()

    async def synchronize_writes(updated: Item):
        nonlocal writers_waiting
        writers_waiting += 1
        if writers_waiting == 2:
            both_read.set()
        await asyncio.wait_for(both_read.wait(), timeout=1)
        await real_upsert(updated)

    monkeypatch.setattr(brain.index, "upsert", synchronize_writes)

    await asyncio.gather(
        brain.update(item.id, content="new content"),
        brain.update(item.id, tags=["new-tag"]),
    )

    stored = await brain.get(item.id)
    assert stored is not None
    assert stored.content == "new content"
    assert stored.tags == ["new-tag"]


async def test_concurrent_adds_cannot_rollback_each_other(
    brain: ThinkTape, tmp_path: Path, monkeypatch,
):
    """A second writer must wait rather than roll back the first transaction."""
    audio = tmp_path / "first.ogg"
    audio.write_bytes(b"first-audio")
    first_in_transaction = asyncio.Event()
    release_first = asyncio.Event()
    original_promote = brain.asset_store.promote

    async def pause_first_promotion(staged):
        await original_promote(staged)
        if staged.assets:
            first_in_transaction.set()
            await release_first.wait()

    monkeypatch.setattr(brain.asset_store, "promote", pause_first_promotion)
    first_task = asyncio.create_task(brain.add("first", audio_path=audio))
    await asyncio.wait_for(first_in_transaction.wait(), timeout=1)
    second_task = asyncio.create_task(brain.add("second"))
    await asyncio.sleep(0.05)
    release_first.set()

    first, second = await asyncio.gather(first_task, second_task)
    stored = await brain.list(status=None)
    assert {item.id for item in stored} == {first.id, second.id}


async def test_add_cancellation_cleans_promoted_assets_and_transaction(
    brain: ThinkTape, config: Config, tmp_path: Path, monkeypatch,
):
    audio = tmp_path / "cancel.ogg"
    audio.write_bytes(b"cancel-me")
    promoted = asyncio.Event()
    release = asyncio.Event()
    original_promote = brain.asset_store.promote

    async def pause_after_promote(staged):
        await original_promote(staged)
        if staged.assets:
            promoted.set()
            await release.wait()

    monkeypatch.setattr(brain.asset_store, "promote", pause_after_promote)
    task = asyncio.create_task(brain.add("cancelled", audio_path=audio))
    await asyncio.wait_for(promoted.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await brain.list(status=None) == []
    assert not any(
        path.name != ".staging" for path in config.assets_dir.iterdir()
    ) if config.assets_dir.exists() else True
    survivor = await brain.add("connection still usable")
    assert (await brain.get(survivor.id)).content == "connection still usable"


async def test_add_double_cancellation_during_commit_keeps_committed_asset(
    brain: ThinkTape, config: Config, tmp_path: Path, monkeypatch,
):
    audio = tmp_path / "double-cancel.ogg"
    audio.write_bytes(b"committed-with-row")
    commit_started = asyncio.Event()
    allow_commit = asyncio.Event()
    commit_landed = asyncio.Event()
    real_commit = brain.index.db.commit
    real_rollback = brain.index.db.rollback

    async def delayed_commit():
        commit_started.set()
        await allow_commit.wait()
        await real_commit()
        commit_landed.set()

    async def rollback_after_commit():
        await commit_landed.wait()
        await real_rollback()

    monkeypatch.setattr(brain.index.db, "commit", delayed_commit)
    monkeypatch.setattr(brain.index.db, "rollback", rollback_after_commit)

    task = asyncio.create_task(brain.add("double cancelled", audio_path=audio))
    await asyncio.wait_for(commit_started.wait(), timeout=1)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    allow_commit.set()

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)

    async with brain.index.db.execute("SELECT id FROM items") as cursor:
        row = await cursor.fetchone()
    assert row is not None
    asset_path = config.assets_dir / row["id"] / "audio.ogg"
    assert asset_path.read_bytes() == b"committed-with-row"


async def test_add_baseexception_cleans_promoted_assets_and_transaction(
    brain: ThinkTape, config: Config, tmp_path: Path, monkeypatch,
):
    audio = tmp_path / "fatal.ogg"
    audio.write_bytes(b"fatal")
    original_promote = brain.asset_store.promote

    async def promote_then_abort(staged):
        await original_promote(staged)
        if staged.assets:
            raise FatalTestError("abort")

    monkeypatch.setattr(brain.asset_store, "promote", promote_then_abort)
    with pytest.raises(FatalTestError):
        await brain.add("fatal", audio_path=audio)

    assert await brain.list(status=None) == []
    assert not any(
        path.name != ".staging" for path in config.assets_dir.iterdir()
    ) if config.assets_dir.exists() else True
    survivor = await brain.add("connection still usable")
    assert await brain.get(survivor.id) is not None


async def test_hard_delete_cancellation_before_commit_restores_assets(
    brain: ThinkTape, config: Config, tmp_path: Path, monkeypatch,
):
    audio = tmp_path / "delete-cancel.ogg"
    audio.write_bytes(b"keep-on-cancel")
    item = await brain.add("keep", audio_path=audio)
    moved = asyncio.Event()
    release = asyncio.Event()
    original_delete = brain.index._delete

    async def pause_delete(item_id):
        moved.set()
        await release.wait()
        await original_delete(item_id)

    monkeypatch.setattr(brain.index, "_delete", pause_delete)
    task = asyncio.create_task(brain.hard_delete(item.id))
    await asyncio.wait_for(moved.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await brain.get(item.id) is not None
    assert (config.assets_dir / item.id / "audio.ogg").read_bytes() == b"keep-on-cancel"
    assert not (config.assets_dir / ".trash" / item.id).exists()


async def test_restart_recovers_interrupted_hard_delete_before_db_commit(tmp_path: Path):
    config = Config(data_dir=tmp_path)
    audio = tmp_path / "crash-before.ogg"
    audio.write_bytes(b"recover-me")
    first = ThinkTape(config)
    await first.connect()
    item = await first.add("survives crash", audio_path=audio)
    await first.close()

    asset_dir = config.assets_dir / item.id
    trash_dir = config.assets_dir / ".trash" / item.id
    trash_dir.parent.mkdir(parents=True)
    asset_dir.replace(trash_dir)

    restarted = ThinkTape(config)
    await restarted.connect()
    try:
        assert await restarted.get(item.id) is not None
        assert (asset_dir / "audio.ogg").read_bytes() == b"recover-me"
        assert not trash_dir.exists()
    finally:
        await restarted.close()


async def test_restart_finishes_interrupted_hard_delete_after_db_commit(tmp_path: Path):
    config = Config(data_dir=tmp_path)
    audio = tmp_path / "crash-after.ogg"
    audio.write_bytes(b"delete-after-commit")
    first = ThinkTape(config)
    await first.connect()
    item = await first.add("deleted before crash", audio_path=audio)
    asset_dir = config.assets_dir / item.id
    trash_dir = config.assets_dir / ".trash" / item.id
    trash_dir.parent.mkdir(parents=True)
    asset_dir.replace(trash_dir)
    await first.index.delete(item.id)
    await first.close()

    restarted = ThinkTape(config)
    await restarted.connect()
    try:
        assert await restarted.get(item.id) is None
        assert not trash_dir.exists()
        assert not asset_dir.exists()
    finally:
        await restarted.close()


async def test_restart_ignores_symlinked_trash_root_without_touching_external_target(
    tmp_path: Path,
):
    config = Config(data_dir=tmp_path)
    first = ThinkTape(config)
    await first.connect()
    await first.close()

    outside = tmp_path / "outside-trash"
    external_item = outside / "20250102-030405-cafe"
    external_item.mkdir(parents=True)
    sentinel = external_item / "sentinel.txt"
    sentinel.write_bytes(b"must-survive")
    config.assets_dir.mkdir(parents=True, exist_ok=True)
    (config.assets_dir / ".trash").symlink_to(outside, target_is_directory=True)

    restarted = ThinkTape(config)
    await restarted.connect()
    try:
        assert sentinel.read_bytes() == b"must-survive"
        assert (config.assets_dir / ".trash").is_symlink()
    finally:
        await restarted.close()


async def test_hard_delete_rejects_malicious_db_item_id_without_touching_outside(
    brain: ThinkTape, config: Config, tmp_path: Path,
):
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_bytes(b"safe")
    now = datetime.now(timezone.utc)
    malicious_id = "../outside"
    await brain.index.upsert(Item(
        id=malicious_id,
        created_at=now,
        updated_at=now,
        type="thought",
        source="api",
        content="malicious db row",
    ))

    with pytest.raises(ValueError, match="invalid item id"):
        await brain.hard_delete(malicious_id)

    assert sentinel.read_bytes() == b"safe"
    assert await brain.index.get(malicious_id) is not None


async def test_hard_delete_rejects_malicious_db_asset_path_without_touching_outside(
    brain: ThinkTape, config: Config, tmp_path: Path,
):
    item = await brain.add("malicious asset row")
    outside = tmp_path / "outside-asset"
    outside.mkdir()
    sentinel = outside / "sentinel.txt"
    sentinel.write_bytes(b"safe")
    await brain.index.db.execute(
        """
        INSERT INTO assets(item_id, path, kind, sha256, byte_size, created_at)
        VALUES(?, ?, 'image', ?, 4, ?)
        """,
        (item.id, "../outside-asset/sentinel.txt", "0" * 64, item.created_at.isoformat()),
    )
    await brain.index.db.commit()

    with pytest.raises(ValueError, match="asset path"):
        await brain.hard_delete(item.id)

    assert sentinel.read_bytes() == b"safe"
    assert await brain.get(item.id) is not None
