"""Tests for FastAPI endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from braindump.config import Config, WebConfig
from braindump.core import BrainDump
from braindump.web import create_app


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    cfg = Config(data_dir=tmp_path, web=WebConfig(host="127.0.0.1", port=0))
    brain = BrainDump(cfg)
    await brain.connect()
    app = create_app(cfg, brain=brain)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, brain
    await brain.close()


async def test_create_and_list(client):
    ac, brain = client
    r = await ac.post("/api/items", json={"content": "from web"})
    assert r.status_code == 200
    data = r.json()
    assert data["content"] == "from web"
    assert data["source"] == "web"

    r = await ac.get("/api/items")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["content"] == "from web"


async def test_get_404(client):
    ac, _ = client
    r = await ac.get("/api/items/nonexistent")
    assert r.status_code == 404


async def test_patch(client):
    ac, _ = client
    r = await ac.post("/api/items", json={"content": "hi"})
    item_id = r.json()["id"]
    r = await ac.patch(f"/api/items/{item_id}", json={"tags": ["x"], "content": "hi2"})
    assert r.status_code == 200
    data = r.json()
    assert data["tags"] == ["x"]
    assert data["content"] == "hi2"


async def test_delete_soft(client):
    ac, _ = client
    r = await ac.post("/api/items", json={"content": "doomed"})
    item_id = r.json()["id"]
    r = await ac.delete(f"/api/items/{item_id}")
    assert r.status_code == 200
    r = await ac.get("/api/items")
    assert r.json()["items"] == []


async def test_stats(client):
    ac, _ = client
    await ac.post("/api/items", json={"content": "a"})
    await ac.post("/api/items", json={"content": "b", "type": "bookmark", "bookmark_url": "https://x"})
    r = await ac.get("/api/stats")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 2
    assert data["by_type"]["thought"] == 1
    assert data["by_type"]["bookmark"] == 1


async def test_search_endpoint(client):
    ac, _ = client
    await ac.post("/api/items", json={"content": "apple pie"})
    await ac.post("/api/items", json={"content": "banana bread"})
    r = await ac.get("/api/items", params={"q": "apple"})
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["content"] == "apple pie"


async def test_healthz(client):
    ac, _ = client
    r = await ac.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_image_serving(client, tmp_path):
    ac, brain = client
    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0\x00")
    item = await brain.add("hi", image_paths=[img])
    r = await ac.get(f"/api/items/{item.id}/images/001.jpg")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff\xe0\x00"
