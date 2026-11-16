"""faster-whisper Local CPU/GPU Speech-to-Text Provider."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional
import numpy as np

from zoro.voice.models import STTConfig, STTResult
from zoro.voice.stt.base import BaseSTTProvider

logger = logging.getLogger(__name__)


class FasterWhisperProvider(BaseSTTProvider):
    """Local Speech-to-Text engine using faster-whisper (CTranslate2)."""

    def __init__(self, config: Optional[STTConfig] = None) -> None:
        super().__init__(config)
        self._model = None

    @property
    def name(self) -> str:
        return "faster-whisper"

    async def load(self) -> bool:
        if self._is_loaded and self._model is not None:
            return True

        def _sync_load():
            from faster_whisper import WhisperModel
            logger.info(
                "Loading faster-whisper '%s' on %s (%s)...",
                self.config.model_name,
                self.config.device,
                self.config.compute_type,
            )
            # Guarantee 100% offline loading without outbound network attempts if cached
            try:
                return WhisperModel(
                    self.config.model_name,
                    device=self.config.device,
                    compute_type=self.config.compute_type,
                    local_files_only=True,
                )
            except Exception:
                return WhisperModel(
                    self.config.model_name,
                    device=self.config.device,
                    compute_type=self.config.compute_type,
                )

        try:
            self._model = await asyncio.to_thread(_sync_load)
            self._is_loaded = True
            logger.info("faster-whisper '%s' model loaded successfully.", self.config.model_name)
            return True
        except Exception as e:
            logger.error("Failed to load faster-whisper model: %s", e)
            self._is_loaded = False
            self._model = None
            return False

    async def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        self._is_loaded = False
        logger.info("faster-whisper model unloaded.")

    async def health_check(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
            return True
        except ImportError:
            return False

    async def transcribe(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = "en",
    ) -> STTResult:
        if not pcm_bytes:
            return STTResult(transcript="", confidence=1.0, duration_ms=0.0)

        if not self._is_loaded or self._model is None:
            loaded = await self.load()
            if not loaded:
                raise RuntimeError("faster-whisper model could not be loaded.")

        start_time = time.perf_counter()

        def _sync_transcribe() -> STTResult:
            samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            segments, info = self._model.transcribe(
                samples,
                language=language or self.config.language,
                beam_size=self.config.beam_size,
                vad_filter=True,
            )

            text_parts = []
            words = []
            for segment in segments:
                text_parts.append(segment.text.strip())
                if segment.words:
                    for w in segment.words:
                        words.append({
                            "word": w.word,
                            "start": w.start,
                            "end": w.end,
                            "probability": w.probability,
                        })

            full_transcript = " ".join(text_parts).strip()
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            detected_lang = info.language if info else (language or "en")
            confidence = info.language_probability if info else 1.0

            return STTResult(
                transcript=full_transcript,
                confidence=confidence,
                duration_ms=duration_ms,
                language=detected_lang,
                is_final=True,
                words=words,
            )

        return await asyncio.to_thread(_sync_transcribe)
