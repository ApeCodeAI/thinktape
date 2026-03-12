"""faster-whisper transcription engine."""

from braindump.transcribe.engine import TranscribeEngine, TranscribeResult


class WhisperEngine(TranscribeEngine):
    """faster-whisper engine for multi-language transcription."""

    def __init__(self, model_size: str = "medium", device: str = "cpu"):
        self.model_size = model_size
        self.device = device
        self._model = None

    def is_available(self) -> bool:
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    def _load_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(self.model_size, device=self.device)

    async def transcribe(self, audio_path: str) -> TranscribeResult:
        import asyncio
        self._load_model()

        loop = asyncio.get_event_loop()
        segments_gen, info = await loop.run_in_executor(
            None, self._model.transcribe, audio_path
        )

        segments = []
        texts = []
        for seg in segments_gen:
            segments.append({
                "start": seg.start,
                "end": seg.end,
                "text": seg.text.strip(),
            })
            texts.append(seg.text.strip())

        return TranscribeResult(
            text=" ".join(texts),
            segments=segments,
            model=f"whisper-{self.model_size}",
            language=info.language,
            duration=info.duration,
        )
