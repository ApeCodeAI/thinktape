"""Tests for FastAPI endpoints."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from thinktape.config import Config, WebConfig
from thinktape.core import ThinkTape
from thinktape.web import create_app


@pytest_asyncio.fixture
async def client(tmp_path: Path):
    cfg = Config(data_dir=tmp_path, web=WebConfig(host="127.0.0.1", port=0))
    brain = ThinkTape(cfg)
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
    ac, brain = client
    image = brain.config.data_dir / "patch-image.jpg"
    image.write_bytes(b"image")
    item = await brain.add("hi", image_paths=[image])
    item_id = item.id
    r = await ac.patch(f"/api/items/{item_id}", json={"tags": ["x"], "content": "hi2"})
    assert r.status_code == 200
    data = r.json()
    assert data["tags"] == ["x"]
    assert data["content"] == "hi2"
    assert data["images"] == ["001.jpg"]


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


async def test_inline_hashtags_in_response_and_filter(client):
    ac, _ = client
    r = await ac.post("/api/items", json={"content": "记录 #工作 想法", "tags": ["手动"]})
    assert r.status_code == 200
    # API exposes the union (explicit + inline) as `tags`.
    assert set(r.json()["tags"]) == {"手动", "工作"}

    # ...and the inline tag is filterable.
    r = await ac.get("/api/items", params={"tag": "工作"})
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["content"] == "记录 #工作 想法"

    # tag list endpoint includes the inline tag too.
    r = await ac.get("/api/tags")
    assert "工作" in r.json()["tags"]


@asynccontextmanager
async def _remote_client(tmp_path):
    """A client whose requests appear to come from a non-loopback (LAN) host."""
    cfg = Config(data_dir=tmp_path, web=WebConfig(host="127.0.0.1", port=0))
    brain = ThinkTape(cfg)
    await brain.connect()
    app = create_app(cfg, brain=brain)
    transport = ASGITransport(app=app, client=("10.0.0.42", 55555))
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await brain.close()


async def test_remote_api_rejected_until_cli_pairing(tmp_path):
    # Bootstrap via the local CLI; never expose an unauthenticated remote API.
    async with _remote_client(tmp_path) as ac:
        r = await ac.post("/api/items", json={"content": "no auth yet"})
        assert r.status_code == 401
        assert (await ac.post("/api/pair", json={"name": "attacker"})).status_code == 401


async def test_auth_enforced_after_pairing(tmp_path):
    from thinktape.auth import DeviceKeyStore

    entry = DeviceKeyStore(tmp_path).add("phone")  # same data_dir as the app
    async with _remote_client(tmp_path) as ac:
        # Remote without a key is now rejected.
        assert (await ac.get("/api/items")).status_code == 401
        # Wrong key rejected; correct key accepted.
        assert (await ac.get("/api/items", headers={"X-ThinkTape-Key": "wrong"})).status_code == 401
        assert (await ac.get("/api/items", headers={"X-ThinkTape-Key": entry["key"]})).status_code == 200
        # Non-API routes (e.g. health) stay open so the web UI can always load.
        assert (await ac.get("/healthz")).status_code == 200


async def test_pair_endpoint_requires_existing_key_even_on_loopback(client, tmp_path):
    from thinktape.auth import DeviceKeyStore

    ac, _ = client
    assert (await ac.post("/api/pair", json={"name": "laptop"})).status_code == 401
    entry = DeviceKeyStore(tmp_path).add("bootstrap-cli")
    r = await ac.post("/api/pair", json={"name": "laptop"})
    assert r.status_code == 401
    r = await ac.post("/api/pair", json={"name": "laptop"},
                      headers={"X-ThinkTape-Key": entry["key"]})
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "laptop" and len(data["key"]) > 10


async def test_upload_item_with_image(client):
    ac, _ = client
    files = {"images": ("photo.jpg", b"\xff\xd8\xff\xe0\x00", "image/jpeg")}
    data = {"content": "带图 #相册", "type": "thought", "tags": "手动"}
    r = await ac.post("/api/items/upload", files=files, data=data)
    assert r.status_code == 200
    d = r.json()
    assert d["has_images"] is True
    assert d["source"] == "app"
    assert set(d["tags"]) >= {"相册", "手动"}


async def test_upload_audio_keeps_content_without_queue(client):
    ac, _ = client
    files = {"audio": ("memo.m4a", b"\x00\x01\x02\x03", "audio/mp4")}
    r = await ac.post("/api/items/upload", files=files, data={"content": "语音备注"})
    assert r.status_code == 200
    d = r.json()
    assert d["has_audio"] is True
    assert d["content"] == "语音备注"


async def test_healthz(client):
    ac, _ = client
    r = await ac.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


async def test_http_migration_endpoint_is_not_exposed(client):
    ac, _ = client
    response = await ac.post("/api/migrate-legacy")
    # Starlette may report either no matching path or method-not-allowed when
    # another non-POST route shares the path shape. Both prove no write API exists.
    assert response.status_code in {404, 405}


async def test_image_serving(client, tmp_path):
    ac, brain = client
    img = tmp_path / "test.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0\x00")
    item = await brain.add("hi", image_paths=[img])
    r = await ac.get(f"/api/items/{item.id}/images/001.jpg")
    assert r.status_code == 200
    assert r.content == b"\xff\xd8\xff\xe0\x00"


async def test_media_serving_uses_db_asset_records(client, tmp_path):
    ac, brain = client
    audio = tmp_path / "source.ogg"
    video = tmp_path / "source.mp4"
    image = tmp_path / "source.png"
    audio.write_bytes(b"audio-from-assets")
    video.write_bytes(b"video-from-assets")
    image.write_bytes(b"image-from-assets")
    item = await brain.add(
        "media", audio_path=audio, video_path=video, image_paths=[image],
    )

    assert (await ac.get(f"/api/items/{item.id}/audio")).content == b"audio-from-assets"
    assert (await ac.get(f"/api/items/{item.id}/video")).content == b"video-from-assets"
    image_response = await ac.get(f"/api/items/{item.id}/images/001.png")
    assert image_response.status_code == 200
    assert image_response.content == b"image-from-assets"

    # A file under the asset directory is not serveable without its DB record.
    rogue = brain.config.assets_dir / item.id / "rogue.png"
    rogue.write_bytes(b"not-recorded")
    assert (await ac.get(f"/api/items/{item.id}/images/rogue.png")).status_code == 404


async def test_corrupted_asset_is_not_served(client, tmp_path):
    ac, brain = client
    audio = tmp_path / "corrupt.ogg"
    audio.write_bytes(b"original")
    item = await brain.add("audio", audio_path=audio)
    asset = (await brain.list_assets(item.id, kind="audio"))[0]
    stored = brain.asset_store.path_for(asset)
    stored.chmod(0o644)
    stored.write_bytes(b"tampered")

    response = await ac.get(f"/api/items/{item.id}/audio")
    assert response.status_code == 409
    assert response.json()["detail"] == "asset integrity check failed"


async def test_concept_link_matches_preserve_image_names(client, tmp_path):
    ac, brain = client
    image = tmp_path / "concept.jpg"
    image.write_bytes(b"concept-image")
    target = await brain.add("alpha target", image_paths=[image])
    source = await brain.add("see [[alpha]]")

    response = await ac.get(f"/api/items/{source.id}/links")
    assert response.status_code == 200
    match = response.json()["outgoing"][0]["matches"][0]
    assert match["id"] == target.id
    assert match["images"] == ["001.jpg"]
