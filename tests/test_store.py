"""Tests for immutable assets and the read-only legacy adapter."""
from __future__ import annotations

import re
from pathlib import Path

from thinktape.store import ItemStore, generate_id


def test_legacy_store_is_read_only_and_does_not_create_tree(tmp_path: Path):
    items_dir = tmp_path / "items"
    store = ItemStore(items_dir)

    assert not items_dir.exists()
    assert not hasattr(store, "create")
    assert not hasattr(store, "update")
    assert not hasattr(store, "delete")
    assert not hasattr(store, "hard_delete")


def test_legacy_store_discovers_only_valid_item_directories(tmp_path: Path):
    items_dir = tmp_path / "items"
    valid_ids = ["20250102-030405-abcd", "20250101-030405-1234"]
    for item_id in valid_ids:
        (items_dir / item_id).mkdir(parents=True)
    (items_dir / "not-an-item").mkdir()
    (items_dir / "20250103-030405-beef").write_text("not a directory")

    store = ItemStore(items_dir)
    assert list(store.iter_ids()) == sorted(valid_ids)


def test_legacy_media_discovery_is_read_only(tmp_path: Path):
    item_id = "20250102-030405-abcd"
    item_dir = tmp_path / "items" / item_id
    images = item_dir / "images"
    images.mkdir(parents=True)
    (item_dir / "audio.ogg").write_bytes(b"audio")
    (item_dir / "video.mp4").write_bytes(b"video")
    (images / "002.png").write_bytes(b"two")
    (images / "001.jpg").write_bytes(b"one")

    store = ItemStore(tmp_path / "items")
    assert store.audio_file(item_id).name == "audio.ogg"
    assert store.video_file(item_id).name == "video.mp4"
    assert [path.name for path in store.image_files(item_id)] == ["001.jpg", "002.png"]


def test_generate_id_unique_and_well_formed():
    ids = {generate_id() for _ in range(100)}
    assert len(ids) > 95
    assert all(re.match(r"^\d{8}-\d{6}-[0-9a-f]{4}$", item_id) for item_id in ids)
