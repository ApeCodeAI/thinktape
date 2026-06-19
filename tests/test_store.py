"""Tests for ItemStore."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest
import yaml

from braindump.store import ItemStore, generate_id


async def test_create_thought(tmp_path: Path):
    store = ItemStore(tmp_path / "items")
    item = await store.create(content="hello world", type="thought")

    assert re.match(r"^\d{8}-\d{6}-[0-9a-f]{4}$", item.id)
    yaml_file = store.yaml_path(item.id)
    content_file = store.content_path(item.id)
    assert yaml_file.exists()
    assert content_file.exists()
    assert content_file.read_text() == "hello world"

    with yaml_file.open() as f:
        data = yaml.safe_load(f)
    assert data["id"] == item.id
    assert data["type"] == "thought"
    assert data["status"] == "active"
    assert data["has_audio"] is False


async def test_get_round_trip(tmp_path: Path):
    store = ItemStore(tmp_path / "items")
    item = await store.create(content="round trip", tags=["a", "b"])
    again = await store.get(item.id)
    assert again is not None
    assert again.content == "round trip"
    assert again.tags == ["a", "b"]


async def test_update_content_and_tags(tmp_path: Path):
    store = ItemStore(tmp_path / "items")
    item = await store.create(content="v1")
    await asyncio.sleep(0.01)
    updated = await store.update(item.id, content="v2", tags=["new"])
    assert updated.content == "v2"
    assert updated.tags == ["new"]
    assert updated.updated_at >= item.created_at


async def test_soft_delete(tmp_path: Path):
    store = ItemStore(tmp_path / "items")
    item = await store.create(content="bye")
    assert await store.delete(item.id) is True
    again = await store.get(item.id)
    assert again is not None and again.status == "deleted"


async def test_audio_copy(tmp_path: Path):
    src = tmp_path / "src.opus"
    src.write_bytes(b"OggS-fake")
    store = ItemStore(tmp_path / "items")
    item = await store.create(content="", audio_path=src)
    assert item.has_audio
    assert store.audio_file(item.id) is not None


async def test_image_copy(tmp_path: Path):
    src1 = tmp_path / "a.jpg"
    src2 = tmp_path / "b.png"
    src1.write_bytes(b"\xff\xd8\xff\xe0")
    src2.write_bytes(b"\x89PNG")
    store = ItemStore(tmp_path / "items")
    item = await store.create(content="pic", image_paths=[src1, src2])
    assert item.has_images
    files = store.image_files(item.id)
    assert len(files) == 2
    assert files[0].name == "001.jpg"
    assert files[1].name == "002.png"


def test_generate_id_unique():
    ids = {generate_id() for _ in range(100)}
    # 100 ids in the same second should yield 100 unique values (4-hex random).
    assert len(ids) > 95


async def test_iter_ids_sorted(tmp_path: Path):
    store = ItemStore(tmp_path / "items")
    for _ in range(3):
        await store.create(content="x")
    ids = list(store.iter_ids())
    assert ids == sorted(ids)
