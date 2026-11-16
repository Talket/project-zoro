"""Deterministic Mock Text-to-Speech Provider for Testing and CI."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, List, Optional
import numpy as np

from zoro.voice.models import TTSAudioChunk, TTSConfig
from zoro.voice.tts.base import BaseTTSProvider


class MockTTSProvider(BaseTTSProvider):
    """Deterministic Text-to-Speech provider generating synthetic PCM audio for testing."""

    def __init__(self, config: Optional[TTSConfig] = None) -> None:
        super().__init__(config)
        self.synthesize_call_count = 0
        self.last_text_synthesized: Optional[str] = None
        self.should_fail: bool = False

    @property
    def name(self) -> str:
        return "mock"

    async def load(self) -> bool:
        self._is_loaded = True
        return True

    async def unload(self) -> None:
        self._is_loaded = False

    async def health_check(self) -> bool:
        return not self.should_fail

    async def list_voices(self) -> List[str]:
        return ["Mock Voice Male", "Mock Voice Female"]

    def _generate_synthetic_pcm(self, duration_ms: float = 200.0) -> bytes:
        """Generate a short 440Hz sine wave tone as int16 PCM."""
        sample_rate = self.config.sample_rate
        num_samples = int(sample_rate * (duration_ms / 1000.0))
        t = np.linspace(0, duration_ms / 1000.0, num_samples, endpoint=False)
        wave = (0.2 * np.sin(2 * np.pi * 440.0 * t) * 32767).astype(np.int16)
        return wave.tobytes()

    async def synthesize(self, text: str, voice: Optional[str] = None, speed: float = 1.0) -> bytes:
        if self.should_fail:
            raise RuntimeError("Simulated TTS synthesis failure.")

        self.synthesize_call_count += 1
        self.last_text_synthesized = text
        return self._generate_synthetic_pcm(duration_ms=150.0)

    async def synthesize_stream(
        self, text: str, voice: Optional[str] = None, speed: float = 1.0
    ) -> AsyncIterator[TTSAudioChunk]:
        if self.should_fail:
            raise RuntimeError("Simulated TTS stream failure.")

        self.synthesize_call_count += 1
        self.last_text_synthesized = text

        # Yield two synthetic chunks
        chunk1 = self._generate_synthetic_pcm(duration_ms=80.0)
        yield TTSAudioChunk(
            pcm_bytes=chunk1,
            sample_rate=self.config.sample_rate,
            duration_ms=80.0,
            is_final=False,
        )

        chunk2 = self._generate_synthetic_pcm(duration_ms=80.0)
        yield TTSAudioChunk(
            pcm_bytes=chunk2,
            sample_rate=self.config.sample_rate,
            duration_ms=80.0,
            is_final=True,
        )
