"""Base Interface for Text-to-Speech Providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, List, Optional

from zoro.voice.models import TTSAudioChunk, TTSConfig


class BaseTTSProvider(ABC):
    """Abstract base class for all local Text-to-Speech providers."""

    def __init__(self, config: Optional[TTSConfig] = None) -> None:
        self.config = config or TTSConfig()
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
        """Initialize provider runtime."""
        pass

    @abstractmethod
    async def unload(self) -> None:
        """Clean up resources."""
        pass

    @abstractmethod
    async def synthesize(self, text: str, voice: Optional[str] = None, speed: float = 1.0) -> bytes:
        """Synthesize text into raw int16 PCM audio bytes."""
        pass

    @abstractmethod
    async def synthesize_stream(
        self, text: str, voice: Optional[str] = None, speed: float = 1.0
    ) -> AsyncIterator[TTSAudioChunk]:
        """Stream synthesized audio chunks incrementally."""
        pass

    @abstractmethod
    async def list_voices(self) -> List[str]:
        """List available voices."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify provider availability."""
        pass
