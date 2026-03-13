"""Transcribe engine interface and async worker."""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from braindump.config import get_config, get_timezone
from braindump.database import get_db

logger = logging.getLogger("braindump.transcribe")


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
    """Fallback engine when no real transcription backend is available.

    Raises an error so that notes are marked 'failed' with a clear message
    instead of silently writing fake transcripts.
    """

    async def transcribe(self, audio_path: str) -> TranscribeResult:
        raise RuntimeError(
            "No transcription engine available. "
            "Install funasr or whisper, or configure an API provider."
        )

    def is_available(self) -> bool:
        return False


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
        logger.warning("FunASR not available, falling back to mock engine")
        return MockEngine()

    elif engine_name == "whisper":
        try:
            from braindump.transcribe.whisper_engine import WhisperEngine
            engine = WhisperEngine(cfg.transcribe.whisper_model, cfg.transcribe.whisper_device)
            if engine.is_available():
                return engine
        except ImportError:
            pass
        logger.warning("Whisper not available, falling back to mock engine")
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
        "transcribed_at": datetime.now(get_timezone()).isoformat(),
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

        # Startup scan: reset stuck 'processing' notes back to 'pending'
        await self._reset_stuck_notes()

        logger.info("Transcribe worker started (engine: %s)", type(self.engine).__name__)

        # Re-enqueue any pending notes from DB
        await self._enqueue_pending()

        while self._running:
            try:
                note_id, file_path = await asyncio.wait_for(self.queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue

            await self._process(note_id, file_path)

    async def _reset_stuck_notes(self):
        """Reset notes stuck in 'processing' state (from previous crash)."""
        db = await get_db()
        try:
            cursor = await db.execute(
                "UPDATE notes SET transcribe_status = 'pending' WHERE transcribe_status = 'processing'"
            )
            await db.commit()
            if cursor.rowcount > 0:
                logger.info("Reset %d stuck transcription(s) from 'processing' to 'pending'", cursor.rowcount)
        finally:
            await db.close()

    async def _enqueue_pending(self):
        """Enqueue any notes with pending transcription status."""
        db = await get_db()
        try:
            cursor = await db.execute(
                "SELECT id, file_path FROM notes WHERE transcribe_status = 'pending' AND file_path IS NOT NULL"
            )
            rows = await cursor.fetchall()
            for row in rows:
                await self.queue.put((row[0], row[1]))
            if rows:
                logger.info("Enqueued %d pending transcription(s)", len(rows))
        finally:
            await db.close()

    async def _process(self, note_id: int, file_path: str):
        cfg = get_config()
        abs_path = cfg.data_dir / file_path

        if not abs_path.exists():
            logger.error("Transcribe error: file not found: %s (note_id=%d)", abs_path, note_id)
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE notes SET transcribe_status = 'failed' WHERE id = ?",
                    (note_id,),
                )
                await db.commit()
            finally:
                await db.close()
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

        # Extract audio from video if needed
        input_path = str(abs_path)
        temp_audio = None
        video_exts = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
        if abs_path.suffix.lower() in video_exts:
            temp_audio = await _extract_audio(abs_path, cfg)
            if temp_audio:
                input_path = str(temp_audio)
                logger.info("Extracted audio from video for note #%d", note_id)

        try:
            result = await self.engine.transcribe(input_path)

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

            logger.info("Transcribed note #%d: %s...", note_id, result.text[:50])

        except Exception as e:
            logger.error("Transcribe failed for note #%d: %s", note_id, e, exc_info=True)
            db = await get_db()
            try:
                await db.execute(
                    "UPDATE notes SET transcribe_status = 'failed' WHERE id = ?",
                    (note_id,),
                )
                await db.commit()
            finally:
                await db.close()
        finally:
            # Clean up temporary audio file
            if temp_audio and temp_audio.exists():
                try:
                    temp_audio.unlink()
                except OSError:
                    pass

    def stop(self):
        self._running = False

    def queue_size(self) -> int:
        """Return current queue size for health checks."""
        return self.queue.qsize()


async def _extract_audio(video_path: Path, cfg) -> Path | None:
    """Extract audio track from video using ffmpeg.

    Returns path to extracted audio file, or None on failure.
    """
    tmp_dir = cfg.data_dir / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    audio_path = tmp_dir / f"{video_path.stem}.ogg"

    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-i", str(video_path),
            "-vn", "-acodec", "libopus",
            "-y",  # overwrite
            str(audio_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error("ffmpeg audio extraction failed: %s", stderr.decode(errors="replace")[-500:])
            return None

        if audio_path.exists() and audio_path.stat().st_size > 0:
            return audio_path

        return None
    except FileNotFoundError:
        logger.error("ffmpeg not found — cannot extract audio from video")
        return None
    except Exception as e:
        logger.error("Audio extraction failed: %s", e)
        return None


def cleanup_old_tmp_files(cfg, max_age_hours: int = 1) -> int:
    """Clean up orphaned temp files older than max_age_hours.

    Returns number of files removed.
    """
    tmp_dir = cfg.data_dir / "tmp"
    if not tmp_dir.exists():
        return 0

    import time
    now = time.time()
    cutoff = now - max_age_hours * 3600
    removed = 0

    for f in tmp_dir.iterdir():
        if f.is_file() and f.stat().st_mtime < cutoff:
            try:
                f.unlink()
                removed += 1
            except OSError:
                pass

    if removed:
        logger.info("Cleaned up %d orphaned temp file(s)", removed)
    return removed
