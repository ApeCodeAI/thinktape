"""Tests for DB-backed transcription media discovery."""
from __future__ import annotations

from pathlib import Path

from thinktape.core import AssetIntegrityError, ThinkTape
from thinktape.transcribe import TranscribeQueue


async def test_transcribe_process_uses_asset_record(brain: ThinkTape, tmp_path: Path, monkeypatch):
    audio = tmp_path / "memo.ogg"
    audio.write_bytes(b"audio")
    item = await brain.add("[转写中…]", audio_path=audio)
    queue = TranscribeQueue(brain)
    seen: list[Path] = []

    async def fake_transcribe(path: Path) -> str:
        seen.append(path)
        return "transcribed from sqlite asset"

    monkeypatch.setattr(queue.transcriber, "transcribe", fake_transcribe)
    await queue._process(item.id)

    assert seen == [brain.config.assets_dir / item.id / "audio.ogg"]
    assert (await brain.get(item.id)).content == "transcribed from sqlite asset"


async def test_backfill_pending_uses_db_items_and_asset_records(brain: ThinkTape, tmp_path: Path):
    pending_audio = tmp_path / "pending.ogg"
    done_audio = tmp_path / "done.ogg"
    pending_video = tmp_path / "pending.mp4"
    pending_audio.write_bytes(b"pending")
    done_audio.write_bytes(b"done")
    pending_video.write_bytes(b"video")

    pending = await brain.add("", audio_path=pending_audio)
    await brain.add("already transcribed", audio_path=done_audio)
    video = await brain.add("[转写中…]", video_path=pending_video)
    await brain.add("no media")

    queue = TranscribeQueue(brain)
    count = await queue.backfill_pending()

    assert count == 2
    assert {queue.queue.get_nowait(), queue.queue.get_nowait()} == {pending.id, video.id}


async def test_corrupted_asset_fails_closed_before_transcription(
    brain: ThinkTape, tmp_path: Path, monkeypatch,
):
    audio = tmp_path / "corrupt.ogg"
    audio.write_bytes(b"original")
    item = await brain.add("[转写中…]", audio_path=audio)
    asset = (await brain.list_assets(item.id, kind="audio"))[0]
    stored = brain.asset_store.path_for(asset)
    stored.chmod(0o644)
    stored.write_bytes(b"corrupted")
    queue = TranscribeQueue(brain)
    called = False

    async def should_not_transcribe(_path):
        nonlocal called
        called = True
        return "unexpected"

    monkeypatch.setattr(queue.transcriber, "transcribe", should_not_transcribe)
    await queue._process(item.id)

    assert called is False
    assert (await brain.get(item.id)).content.startswith("[转写失败: asset integrity check failed")
