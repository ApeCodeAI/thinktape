"""FunASR transcription engine (Paraformer-large)."""

from braindump.transcribe.engine import TranscribeEngine, TranscribeResult


class FunASREngine(TranscribeEngine):
    """FunASR Paraformer-large engine for Chinese transcription."""

    def __init__(self, model_name: str = "paraformer-zh"):
        self.model_name = model_name
        self._model = None

    def is_available(self) -> bool:
        try:
            import funasr
            return True
        except ImportError:
            return False

    def _load_model(self):
        if self._model is None:
            from funasr import AutoModel
            self._model = AutoModel(model=self.model_name)

    async def transcribe(self, audio_path: str) -> TranscribeResult:
        import asyncio
        self._load_model()

        # Run in thread pool since FunASR is synchronous
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._model.generate, audio_path)

        # Parse FunASR output
        if result and len(result) > 0:
            text = result[0].get("text", "")
            # FunASR may include timestamps in some modes
            segments = []
            if "timestamp" in result[0]:
                for ts in result[0]["timestamp"]:
                    segments.append({
                        "start": ts[0] / 1000.0,
                        "end": ts[1] / 1000.0,
                        "text": "",
                    })
        else:
            text = ""
            segments = []

        return TranscribeResult(
            text=text,
            segments=segments,
            model=self.model_name,
            language="zh",
        )
