"""Piper Local Neural Text-to-Speech Provider."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import AsyncIterator, List, Optional
import numpy as np

from zoro.voice.models import TTSAudioChunk, TTSConfig
from zoro.voice.tts.base import BaseTTSProvider

logger = logging.getLogger(__name__)


class PiperTTSProvider(BaseTTSProvider):
    """Local Neural Text-to-Speech synthesizer using Piper ONNX models."""

    def __init__(self, config: Optional[TTSConfig] = None, model_path: Optional[str] = None) -> None:
        super().__init__(config)
        self.model_path = model_path
        self._voice_instance = None

    @property
    def name(self) -> str:
        return "piper"

    async def load(self) -> bool:
        if self._is_loaded and self._voice_instance is not None:
            return True

        def _sync_load():
            if not self.model_path or not Path(self.model_path).exists():
                logger.debug("Piper model path '%s' not found. Provider will use fallback.", self.model_path)
                return None

            try:
                from piper import PiperVoice
                return PiperVoice.load(self.model_path)
            except Exception as e:
                logger.error("Failed to load Piper voice model: %s", e)
                return None

        self._voice_instance = await asyncio.to_thread(_sync_load)
        self._is_loaded = self._voice_instance is not None
        return self._is_loaded

    async def unload(self) -> None:
        self._voice_instance = None
        self._is_loaded = False

    async def health_check(self) -> bool:
        return self._voice_instance is not None or (self.model_path is not None and Path(self.model_path).exists())

    async def list_voices(self) -> List[str]:
        if self.model_path:
            return [Path(self.model_path).stem]
        return ["en_US-lessac-medium"]

    async def synthesize(self, text: str, voice: Optional[str] = None, speed: float = 1.0) -> bytes:
        if not text.strip():
            return b""

        if not self._is_loaded or self._voice_instance is None:
            loaded = await self.load()
            if not loaded:
                raise RuntimeError("Piper voice model is not loaded.")

        def _sync_synth() -> bytes:
            audio_stream = self._voice_instance.synthesize_stream_raw(text)
            chunks = []
            for chunk in audio_stream:
                chunks.append(chunk)
            return b"".join(chunks)

        return await asyncio.to_thread(_sync_synth)

    async def synthesize_stream(
        self, text: str, voice: Optional[str] = None, speed: float = 1.0
    ) -> AsyncIterator[TTSAudioChunk]:
        if not text.strip():
            return

        if not self._is_loaded or self._voice_instance is None:
            loaded = await self.load()
            if not loaded:
                raise RuntimeError("Piper voice model is not loaded.")

        def _sync_stream():
            return list(self._voice_instance.synthesize_stream_raw(text))

        chunks = await asyncio.to_thread(_sync_stream)
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            duration_ms = (len(chunk) / (self.config.sample_rate * 2)) * 1000.0
            yield TTSAudioChunk(
                pcm_bytes=chunk,
                sample_rate=self.config.sample_rate,
                duration_ms=duration_ms,
                is_final=is_last,
            )
