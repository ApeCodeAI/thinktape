"""Transcribe engine interface and async worker."""

import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path

from braindump.config import get_config
from braindump.database import get_db

TZ_CST = timezone(timedelta(hours=8))


class TranscribeResult:
    """Result from a transcription engine."""

    def __init__(self, text: str, segments: list[dict] | None = None,
                 language: str = "zh", model: str = "", duration: float = 0):
        self.text = text
        self.segments = segments or []
        self.language = language
        self.model = model
        self.duration = duration


class TranscribeEngine(ABC):
    """Abstract base class for transcription engines."""

    @abstractmethod
    async def transcribe(self, audio_path: str) -> TranscribeResult:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...


class MockEngine(TranscribeEngine):
    """Mock transcription engine for testing."""

    async def transcribe(self, audio_path: str) -> TranscribeResult:
        return TranscribeResult(
            text=f"[Mock transcription of {Path(audio_path).name}]",
            segments=[{"start": 0.0, "end": 1.0, "text": "[Mock transcription]"}],
            model="mock",
            language="zh",
            duration=0,
        )

    def is_available(self) -> bool:
        return True


def get_engine() -> TranscribeEngine:
    """Get the configured transcription engine."""
    cfg = get_config()
    engine_name = cfg.transcribe.engine

    if engine_name == "funasr":
        try:
            from braindump.transcribe.funasr_engine import FunASREngine
            engine = FunASREngine(cfg.transcribe.funasr_model)
            if engine.is_available():
                return engine
        except ImportError:
            pass
        print("FunASR not available, falling back to mock engine")
        return MockEngine()

    elif engine_name == "whisper":
        try:
            from braindump.transcribe.whisper_engine import WhisperEngine
            engine = WhisperEngine(cfg.transcribe.whisper_model, cfg.transcribe.whisper_device)
            if engine.is_available():
                return engine
        except ImportError:
            pass
        print("Whisper not available, falling back to mock engine")
        return MockEngine()

    return MockEngine()


def _save_transcript_files(result: TranscribeResult, source_file: str, cfg):
    """Save .txt and .json transcript files."""
    source_path = Path(source_file)
    # Derive transcript path from media path
    # media/video/2026/03/12/xxx.mp4 -> transcripts/2026/03/12/xxx.txt
    parts = source_path.parts
    # Find the date parts after media/{type}/
    try:
        media_idx = parts.index("media")
        date_parts = parts[media_idx + 2:]  # skip media/{type}
    except ValueError:
        date_parts = parts[-4:]  # fallback

    stem = source_path.stem
    transcript_dir = cfg.transcripts_dir / "/".join(str(p) for p in date_parts[:-1])
    transcript_dir.mkdir(parents=True, exist_ok=True)

    # Plain text
    txt_path = transcript_dir / f"{stem}.txt"
    txt_path.write_text(result.text, encoding="utf-8")

    # JSON with timestamps
    json_path = transcript_dir / f"{stem}.json"
    json_data = {
        "source_file": source_file,
        "model": result.model,
        "language": result.language,
        "duration_seconds": result.duration,
        "transcribed_at": datetime.now(TZ_CST).isoformat(),
        "segments": result.segments,
    }
    json_path.write_text(json.dumps(json_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return txt_path, json_path


class TranscribeWorker:
    """Async worker that processes transcription queue."""

    def __init__(self):
        self.queue: asyncio.Queue = asyncio.Queue()
        self.engine: TranscribeEngine | None = None
        self._running = False

    async def enqueue(self, note_id: int, file_path: str):
        await self.queue.put((note_id, file_path))

    async def run(self):
        """Main worker loop — process transcription queue."""
        self._running = True
        self.engine = get_engine()
        print(f"Transcribe worker started (engine: {type(self.engine).__name__})")

        while self._running:
            try:
                note_id, file_path = await asyncio.wait_for(self.queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

            await self._process(note_id, file_path)

    async def _process(self, note_id: int, file_path: str):
        cfg = get_config()
        abs_path = cfg.data_dir / file_path

        if not abs_path.exists():
            print(f"  Transcribe error: file not found: {abs_path}")
            return

        # Update status
        db = await get_db()
        try:
            await db.execute(
                "UPDATE notes SET transcribe_status = 'processing' WHERE id = ?",
                (note_id,),
            )
            await db.commit()
        finally:
            await db.close()

        try:
            result = await self.engine.transcribe(str(abs_path))

            # Save transcript files
            _save_transcript_files(result, file_path, cfg)

            # Update database
            db = await get_db()
            try:
                await db.execute(
                    """UPDATE notes SET transcript = ?, transcribe_status = 'done',
                       duration = COALESCE(duration, ?)
                       WHERE id = ?""",
                    (result.text, result.duration or None, note_id),
                )
                await db.commit()
            finally:
                await db.close()

            print(f"  Transcribed note #{note_id}: {result.text[:50]}...")

        except Exception as e:
            print(f"  Transcribe failed for note #{note_id}: {e}")
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE notes SET transcribe_status = 'failed' WHERE id = ?",
                    (note_id,),
                )
                await db.commit()
            finally:
                await db.close()

    def stop(self):
        self._running = False
