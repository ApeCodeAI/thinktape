"""Durable iPhone recording ingestion and transcription recovery tests."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from stat import S_IMODE

import pytest
from httpx import ASGITransport, AsyncClient

from thinktape.auth import DeviceKeyStore
from thinktape.config import Config, WebConfig
from thinktape.core import ThinkTape
from thinktape.transcribe import TranscribeQueue
from thinktape.web import create_app


def test_device_keys_are_private_on_create_and_rotation(tmp_path: Path):
    store = DeviceKeyStore(tmp_path)
    store.add("iphone")
    assert S_IMODE(store.path.stat().st_mode) == 0o600
    store.add("second-device")
    assert S_IMODE(store.path.stat().st_mode) == 0o600


async def _client_for(
    data_dir: Path, *, queue: TranscribeQueue | None = None, host: str = "10.0.0.42",
):
    config = Config(data_dir=data_dir, web=WebConfig(host="127.0.0.1", port=0))
    brain = ThinkTape(config)
    await brain.connect()
    app = create_app(config, brain=brain, transcribe_queue=queue)
    transport = ASGITransport(app=app, client=(host, 55555))
    client = AsyncClient(transport=transport, base_url="http://test")
    return brain, client


async def _upload(client: AsyncClient, key: str, recording_id: str, payload: bytes, **data):
    form = {"recording_id": recording_id, **data}
    return await client.post(
        "/api/recordings",
        headers={"X-ThinkTape-Key": key},
        files={"audio": ("memo.m4a", payload, "audio/mp4")},
        data=form,
    )


async def _wait_for_status(client: AsyncClient, key: str, recording_id: str, expected: str):
    for _ in range(100):
        response = await client.get(
            f"/api/recordings/{recording_id}",
            headers={"X-ThinkTape-Key": key},
        )
        assert response.status_code == 200
        body = response.json()
        if body["transcription_status"] == expected:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"recording did not reach {expected}: {body}")


@pytest.mark.asyncio
async def test_recording_lost_ack_retry_is_idempotent_and_preserves_edits(tmp_path: Path):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    brain, client = await _client_for(tmp_path)
    try:
        payload = b"same immutable audio bytes"
        first = await _upload(client, key, "iphone-001", payload)
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["recording_id"] == "iphone-001"
        assert body["stored"] is True
        assert body["item_id"] == body["id"]
        assert body["checksum"] == hashlib.sha256(payload).hexdigest()
        assert body["byte_size"] == len(payload)
        assert body["transcription_status"] == "pending"
        item_id = body["item_id"]

        await brain.update(item_id, content="human edited text")
        retry = await _upload(client, key, "iphone-001", payload)
        assert retry.status_code == 200, retry.text
        assert retry.json()["item_id"] == item_id
        assert retry.json()["stored"] is True
        assert retry.json()["content"] == "human edited text"
        assert len(await brain.index.item_ids()) == 1
        assert len(await brain.list_assets(item_id, kind="audio")) == 1
    finally:
        await client.aclose()
        await brain.close()


@pytest.mark.asyncio
async def test_recording_id_conflict_rejected_even_after_original_is_stored(tmp_path: Path):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    brain, client = await _client_for(tmp_path)
    try:
        assert (await _upload(client, key, "iphone-002", b"original")).status_code == 200
        conflict = await _upload(client, key, "iphone-002", b"changed")
        assert conflict.status_code == 409
        assert "recording_id" in conflict.json()["detail"]
        assert len(await brain.index.item_ids()) == 1
    finally:
        await client.aclose()
        await brain.close()


@pytest.mark.asyncio
async def test_simultaneous_same_recording_id_creates_one_item(tmp_path: Path):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    brain_a, client_a = await _client_for(tmp_path)
    brain_b, client_b = await _client_for(tmp_path)
    try:
        responses = await asyncio.gather(
            _upload(client_a, key, "iphone-concurrent", b"concurrent bytes"),
            _upload(client_b, key, "iphone-concurrent", b"concurrent bytes"),
        )
        assert [response.status_code for response in responses] == [200, 200]
        assert responses[0].json()["item_id"] == responses[1].json()["item_id"]
        assert len(await brain_a.index.item_ids()) == 1
        item_id = responses[0].json()["item_id"]
        assert len(await brain_a.list_assets(item_id, kind="audio")) == 1
    finally:
        await client_a.aclose()
        await client_b.aclose()
        await brain_a.close()
        await brain_b.close()


@pytest.mark.asyncio
async def test_empty_recording_is_rejected_without_a_ledger_or_asset(tmp_path: Path):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    brain, client = await _client_for(tmp_path)
    try:
        response = await _upload(client, key, "iphone-empty", b"")
        assert response.status_code == 422
        assert await brain.index.item_ids() == []
        assert not (tmp_path / "assets").exists()
    finally:
        await client.aclose()
        await brain.close()


@pytest.mark.asyncio
async def test_restart_backfills_running_recording_and_transcribes(tmp_path: Path):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    brain, client = await _client_for(tmp_path)
    payload = b"restartable audio"
    try:
        response = await _upload(client, key, "iphone-restart", payload)
        item_id = response.json()["item_id"]
        await brain.index.update_recording_status("iphone-restart", "running")
    finally:
        await client.aclose()
        await brain.close()

    brain2 = ThinkTape(Config(data_dir=tmp_path, web=WebConfig(host="127.0.0.1", port=0)))
    await brain2.connect()
    queue = TranscribeQueue(brain2)
    seen: list[Path] = []

    async def fake_transcribe(path: Path) -> str:
        seen.append(path)
        return "recovered transcript"

    queue.transcriber.transcribe = fake_transcribe
    try:
        assert await queue.backfill_pending() == 1
        assert (await brain2.get_recording("iphone-restart"))["transcription_status"] == "queued"
        await queue._process(item_id)
        status = await brain2.get_recording("iphone-restart")
        assert status["transcription_status"] == "completed"
        assert status["attempts"] == 1
        assert (await brain2.get(item_id)).content == "recovered transcript"
        assert seen == [tmp_path / "assets" / item_id / "audio.m4a"]
    finally:
        await brain2.close()


@pytest.mark.asyncio
async def test_failed_transcription_is_retryable_bounded_and_keeps_original(tmp_path: Path):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    config = Config(data_dir=tmp_path, web=WebConfig(host="127.0.0.1", port=0))
    queue_brain = ThinkTape(config)
    await queue_brain.connect()
    queue = TranscribeQueue(queue_brain)
    client = AsyncClient(
        transport=ASGITransport(
            app=create_app(config, brain=queue_brain, transcribe_queue=queue),
            client=("10.0.0.42", 55555),
        ),
        base_url="http://test",
    )
    calls = 0

    async def always_fails(_path: Path) -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("bad media")

    queue.transcriber.transcribe = always_fails
    try:
        await queue.start()
        response = await _upload(client, key, "iphone-failed", b"not decodable")
        item_id = response.json()["item_id"]
        first_failure = await _wait_for_status(client, key, "iphone-failed", "failed")
        assert first_failure["attempts"] == 1
        assert first_failure["last_error"] == "bad media"
        for attempt in range(2, 4):
            retry = await client.post(
                "/api/recordings/iphone-failed/retry",
                headers={"X-ThinkTape-Key": key},
            )
            assert retry.status_code == 200, retry.text
            failed = await _wait_for_status(client, key, "iphone-failed", "failed")
            assert failed["attempts"] == attempt
            assert failed["last_error"] == "bad media"

        exhausted = await client.post(
            "/api/recordings/iphone-failed/retry",
            headers={"X-ThinkTape-Key": key},
        )
        assert exhausted.status_code == 409
        assert calls == 3
        asset = (await queue_brain.list_assets(item_id, kind="audio"))[0]
        assert queue_brain.asset_store.path_for(asset).read_bytes() == b"not decodable"
        assert (await queue_brain.get(item_id)).content.startswith("[转写中")
    finally:
        await queue.stop()
        await client.aclose()
        await queue_brain.close()


@pytest.mark.asyncio
async def test_retry_after_restart_reuses_receipt_and_original_audio(tmp_path: Path):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    first_brain, first_client = await _client_for(tmp_path)
    try:
        original = await _upload(first_client, key, "restart-receipt", b"durable bytes")
        assert original.status_code == 200
        item_id = original.json()["item_id"]
    finally:
        await first_client.aclose()
        await first_brain.close()

    second_brain, second_client = await _client_for(tmp_path)
    try:
        replay = await _upload(second_client, key, "restart-receipt", b"durable bytes")
        assert replay.status_code == 200
        assert replay.json()["item_id"] == item_id
        assert (await second_brain.media_file(item_id, "audio")).read_bytes() == b"durable bytes"
        assert len(await second_brain.index.item_ids()) == 1
        assert (await _upload(second_client, key, "restart-receipt", b"other bytes")).status_code == 409
    finally:
        await second_client.aclose()
        await second_brain.close()


@pytest.mark.asyncio
async def test_hard_delete_removes_recording_receipt_and_audio(tmp_path: Path):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    brain, client = await _client_for(tmp_path)
    try:
        response = await _upload(client, key, "iphone-disposable", b"disposable test audio")
        assert response.status_code == 200
        item_id = response.json()["item_id"]
        assert await brain.hard_delete(item_id)
        assert await brain.get_recording("iphone-disposable") is None
        assert await brain.get(item_id) is None
        assert not (tmp_path / "assets" / item_id).exists()
    finally:
        await client.aclose()
        await brain.close()


@pytest.mark.asyncio
async def test_promotion_failure_rolls_back_recording_and_files(tmp_path: Path, monkeypatch):
    key = DeviceKeyStore(tmp_path).add("iphone")["key"]
    brain, client = await _client_for(tmp_path)
    promote = brain.asset_store.promote

    async def fail_after_promote(staged):
        await promote(staged)
        raise OSError("disk failure")

    try:
        monkeypatch.setattr(brain.asset_store, "promote", fail_after_promote)
        with pytest.raises(OSError, match="disk failure"):
            await _upload(client, key, "failure-rollback", b"original")
        assert await brain.get_recording("failure-rollback") is None
        assert await brain.index.item_ids() == []
        assert not list(brain.config.assets_dir.glob("*/audio.m4a"))
        monkeypatch.setattr(brain.asset_store, "promote", promote)
        assert (await _upload(client, key, "failure-rollback", b"original")).status_code == 200
    finally:
        await client.aclose()
        await brain.close()


@pytest.mark.asyncio
async def test_duplicate_queue_notifications_do_not_repeat_transcription(tmp_path: Path):
    brain = ThinkTape(Config(data_dir=tmp_path))
    await brain.connect()
    audio = tmp_path / "memo.m4a"
    audio.write_bytes(b"once")
    queue = TranscribeQueue(brain)
    calls = 0

    async def transcribe(_path: Path) -> str:
        nonlocal calls
        calls += 1
        return "once transcribed"

    queue.transcriber.transcribe = transcribe
    try:
        result = await brain.ingest_recording("duplicate-notice", audio)
        await brain.queue_recording("duplicate-notice")
        queue.enqueue(result.item.id)
        queue.enqueue(result.item.id)
        await queue._process(queue.queue.get_nowait())
        await queue._process(queue.queue.get_nowait())
        assert calls == 1
        assert (await brain.get_recording("duplicate-notice"))["attempts"] == 1
        assert (await brain.get_recording("duplicate-notice"))["transcription_status"] == "completed"
    finally:
        await brain.close()


@pytest.mark.asyncio
async def test_two_workers_claim_only_one_transcription(tmp_path: Path):
    cfg = Config(data_dir=tmp_path)
    first, second = ThinkTape(cfg), ThinkTape(cfg)
    await first.connect()
    await second.connect()
    audio = tmp_path / "memo.m4a"
    audio.write_bytes(b"one claim")
    try:
        await first.ingest_recording("worker-claim", audio)
        await first.queue_recording("worker-claim")
        claims = await asyncio.gather(
            first.start_recording_transcription("worker-claim"),
            second.start_recording_transcription("worker-claim"),
        )
        assert sum(claim is not None for claim in claims) == 1
        assert (await first.get_recording("worker-claim"))["attempts"] == 1
    finally:
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_backfill_respects_attempt_limit_and_keeps_failed_audio(tmp_path: Path):
    brain = ThinkTape(Config(data_dir=tmp_path))
    await brain.connect()
    audio = tmp_path / "memo.m4a"
    audio.write_bytes(b"failed audio")
    queue = TranscribeQueue(brain)
    try:
        receipt = await brain.ingest_recording("exhausted-job", audio)
        for _ in range(3):
            await brain.index.update_recording_status(
                "exhausted-job", "failed", increment_attempt=True,
                last_error="bad media",
            )
        assert await queue.backfill_pending() == 0
        assert queue.queue.empty()
        status = await brain.get_recording("exhausted-job")
        assert status["transcription_status"] == "failed"
        assert status["attempts"] == 3
        assert status["last_error"] == "bad media"
        assert (await brain.media_file(receipt.item.id, "audio")).read_bytes() == b"failed audio"
    finally:
        await brain.close()


@pytest.mark.asyncio
async def test_transcription_keeps_edit_made_while_worker_runs(tmp_path: Path):
    brain = ThinkTape(Config(data_dir=tmp_path))
    await brain.connect()
    audio = tmp_path / "memo.m4a"
    audio.write_bytes(b"edited audio")
    queue = TranscribeQueue(brain)
    try:
        receipt = await brain.ingest_recording("edited-during-job", audio)
        await brain.queue_recording("edited-during-job")

        async def transcribe(_path: Path) -> str:
            await brain.update(receipt.item.id, content="human edit")
            return "machine transcript"

        queue.transcriber.transcribe = transcribe
        await queue._process(receipt.item.id)
        assert (await brain.get(receipt.item.id)).content == "human edit"
        assert (await brain.get_recording("edited-during-job"))["transcription_status"] == "completed"
    finally:
        await brain.close()


@pytest.mark.asyncio
async def test_recording_route_requires_paired_key_even_on_loopback(tmp_path: Path):
    brain, client = await _client_for(tmp_path, host="127.0.0.1")
    try:
        response = await client.post(
            "/api/recordings",
            files={"audio": ("memo.m4a", b"audio", "audio/mp4")},
            data={"recording_id": "iphone-auth"},
        )
        assert response.status_code == 401
    finally:
        await client.aclose()
        await brain.close()
