"""Speech-to-Text Provider Registry and Fallback Coordinator."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from zoro.voice.models import STTResult
from zoro.voice.stt.base import BaseSTTProvider
from zoro.voice.stt.faster_whisper import FasterWhisperProvider
from zoro.voice.stt.mock import MockSTTProvider
from zoro.voice.stt.whisper_cpp import WhisperCppProvider

logger = logging.getLogger(__name__)


class STTRegistry:
    """Coordinates available STT providers, active selection, and fallback cascading."""

    def __init__(self, default_provider: str = "faster-whisper") -> None:
        self._providers: Dict[str, BaseSTTProvider] = {}
        self.active_provider_name = default_provider

        # Register built-ins
        self.register_provider(FasterWhisperProvider())
        self.register_provider(WhisperCppProvider())
        self.register_provider(MockSTTProvider())

    def register_provider(self, provider: BaseSTTProvider) -> None:
        """Register an STT provider instance."""
        self._providers[provider.name] = provider
        logger.debug("Registered STT provider: %s", provider.name)

    def get_provider(self, name: str) -> Optional[BaseSTTProvider]:
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    async def set_active_provider(self, name: str) -> bool:
        """Switch active STT provider and load its model."""
        if name not in self._providers:
            logger.error("Unknown STT provider: %s", name)
            return False

        # Unload current provider to save RAM/VRAM
        current = self.get_active_provider()
        if current and current.name != name:
            await current.unload()

        self.active_provider_name = name
        new_provider = self.get_active_provider()
        if new_provider:
            return await new_provider.load()
        return True

    def get_active_provider(self) -> Optional[BaseSTTProvider]:
        return self._providers.get(self.active_provider_name)

    async def transcribe(
        self,
        pcm_bytes: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = "en",
    ) -> STTResult:
        """Transcribe with active provider, automatically falling back if unavailable."""
        provider = self.get_active_provider()
        if not provider:
            raise RuntimeError(f"No active STT provider configured: {self.active_provider_name}")

        try:
            return await provider.transcribe(pcm_bytes, sample_rate, language)
        except Exception as e_primary:
            logger.warning(
                "Primary STT provider '%s' failed (%s). Attempting fallback cascade.",
                provider.name,
                e_primary,
            )
            # Find an operational fallback provider
            for name, fallback in self._providers.items():
                if name != provider.name:
                    try:
                        logger.info("Failing over to fallback STT provider: %s", name)
                        return await fallback.transcribe(pcm_bytes, sample_rate, language)
                    except Exception as e_fb:
                        logger.debug("Fallback STT '%s' failed: %s", name, e_fb)

            raise RuntimeError(f"All STT providers failed. Primary error: {e_primary}")
