"""Faster-whisper transcription worker.

Runs as a background task. Items whose content.md is empty and have audio/video
get transcribed; the transcript replaces content.md and the index is updated.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .config import TranscribeConfig
from .core import ThinkTape
from .models import Item

log = logging.getLogger(__name__)


class Transcriber:
    """Wraps faster-whisper with lazy model loading."""

    def __init__(self, cfg: TranscribeConfig):
        self.cfg = cfg
        self._model = None
        self._lock = asyncio.Lock()

    async def _load(self):
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is not None:
                return self._model
            log.info("loading faster-whisper model %s on %s", self.cfg.whisper_model, self.cfg.whisper_device)
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError(
                    "faster-whisper not installed. Run `uv sync --extra transcribe`."
                ) from e
            self._model = await asyncio.to_thread(
                WhisperModel,
                self.cfg.whisper_model,
                device=self.cfg.whisper_device,
                compute_type="int8" if self.cfg.whisper_device == "cpu" else "float16",
            )
            return self._model

    async def transcribe(self, audio_path: Path) -> str:
        model = await self._load()
        return await asyncio.to_thread(self._transcribe_sync, model, audio_path)

    @staticmethod
    def _transcribe_sync(model, audio_path: Path) -> str:
        segments, _info = model.transcribe(str(audio_path), beam_size=5, vad_filter=True)
        return "".join(seg.text for seg in segments).strip()


class TranscribeQueue:
    """Background worker that transcribes audio/video items as they come in."""

    def __init__(self, brain: ThinkTape):
        self.brain = brain
        self.transcriber = Transcriber(brain.config.transcribe)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    def enqueue(self, item_id: str) -> None:
        self.queue.put_nowait(item_id)

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="transcribe-worker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        log.info("transcribe worker started")
        while True:
            try:
                item_id = await self.queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._process(item_id)
            except Exception:
                log.exception("transcribe failed for %s", item_id)

    async def _process(self, item_id: str) -> None:
        item = await self.brain.get(item_id)
        if item is None:
            log.warning("transcribe: item %s not found", item_id)
            return
        audio = self.brain.store.audio_file(item_id) or self.brain.store.video_file(item_id)
        if audio is None:
            return
        # Don't re-transcribe items that already have content.
        if item.content and not item.content.startswith("[转写中"):
            return

        log.info("transcribing %s (%s)", item_id, audio.name)
        try:
            text = await self.transcriber.transcribe(audio)
        except Exception as e:
            log.exception("transcribe model error: %s", e)
            await self.brain.update(item_id, content=f"[转写失败: {e}]")
            return
        if not text:
            text = "[空音频]"
        await self.brain.update(item_id, content=text)
        log.info("transcribed %s -> %d chars", item_id, len(text))

    async def backfill_pending(self) -> int:
        """Re-enqueue any audio/video items whose content is empty or marked transcribing."""
        n = 0
        for item_id in self.brain.store.iter_ids():
            item: Item | None = await self.brain.store.get(item_id)
            if item is None:
                continue
            if not (item.has_audio or item.has_video):
                continue
            if item.content and not item.content.startswith("[转写中"):
                continue
            self.enqueue(item_id)
            n += 1
        return n
