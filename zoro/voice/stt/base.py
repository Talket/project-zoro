"""Base Interface for Speech-to-Text Providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from zoro.voice.models import STTConfig, STTResult


class BaseSTTProvider(ABC):
    """Abstract base class for all local Speech-to-Text providers."""

    def __init__(self, config: Optional[STTConfig] = None) -> None:
        self.config = config or STTConfig()
        self._is_loaded = False

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""
        pass

    @property
    def is_loaded(self) -> bool:
        return self._is_loaded

    @abstractmethod
    async def load(self) -> bool:
        """Load model weights into memory."""
        pass

    @abstractmethod
    async def unload(self) -> None:
        """Evict model weights from memory to reclaim RAM."""
        pass

    @abstractmethod
    async def transcribe(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = "en",
    ) -> STTResult:
        """Transcribe raw int16 PCM audio into structured STTResult."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify provider availability and runtime operational status."""
        pass
