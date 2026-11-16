"""Deterministic Mock Speech-to-Text Provider for Testing and CI."""

from __future__ import annotations

import asyncio
from typing import List, Optional

from zoro.voice.models import STTConfig, STTResult
from zoro.voice.stt.base import BaseSTTProvider


class MockSTTProvider(BaseSTTProvider):
    """Deterministic Speech-to-Text provider for testing and offline CI environments."""

    def __init__(self, config: Optional[STTConfig] = None) -> None:
        super().__init__(config)
        self.preset_transcriptions: List[str] = []
        self._call_count = 0
        self.simulated_delay_seconds: float = 0.0
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

    def queue_transcription(self, text: str) -> None:
        """Enqueue a canned transcription response."""
        self.preset_transcriptions.append(text)

    async def transcribe(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = "en",
    ) -> STTResult:
        if self.should_fail:
            raise RuntimeError("Simulated STT failure.")

        if self.simulated_delay_seconds > 0:
            await asyncio.sleep(self.simulated_delay_seconds)

        self._call_count += 1
        if self.preset_transcriptions:
            text = self.preset_transcriptions.pop(0)
        else:
            text = "Open Chrome"

        return STTResult(
            transcript=text,
            confidence=0.98,
            duration_ms=45.0,
            language=language or "en",
            is_final=True,
        )
