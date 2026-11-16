"""Text-to-Speech Provider Registry and Fallback Coordinator."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from zoro.voice.tts.base import BaseTTSProvider
from zoro.voice.tts.mock import MockTTSProvider
from zoro.voice.tts.piper import PiperTTSProvider
from zoro.voice.tts.sapi import WindowsSapiTTSProvider

logger = logging.getLogger(__name__)


class TTSRegistry:
    """Coordinates available TTS providers, active voice selection, and fallback cascading."""

    def __init__(self, default_provider: str = "windows-sapi") -> None:
        self._providers: Dict[str, BaseTTSProvider] = {}
        self.active_provider_name = default_provider

        # Register default providers
        self.register_provider(WindowsSapiTTSProvider())
        self.register_provider(PiperTTSProvider())
        self.register_provider(MockTTSProvider())

    def register_provider(self, provider: BaseTTSProvider) -> None:
        """Register a TTS provider instance."""
        self._providers[provider.name] = provider
        logger.debug("Registered TTS provider: %s", provider.name)

    def get_provider(self, name: str) -> Optional[BaseTTSProvider]:
        return self._providers.get(name)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    async def set_active_provider(self, name: str) -> bool:
        """Switch active TTS provider."""
        if name not in self._providers:
            logger.error("Unknown TTS provider: %s", name)
            return False

        current = self.get_active_provider()
        if current and current.name != name:
            await current.unload()

        self.active_provider_name = name
        new_provider = self.get_active_provider()
        if new_provider:
            return await new_provider.load()
        return True

    def get_active_provider(self) -> Optional[BaseTTSProvider]:
        return self._providers.get(self.active_provider_name)

    async def list_voices(self) -> List[str]:
        provider = self.get_active_provider()
        if provider:
            return await provider.list_voices()
        return []

    async def synthesize(self, text: str, voice: Optional[str] = None, speed: float = 1.0) -> bytes:
        """Synthesize text with active provider, automatically falling back if unavailable."""
        provider = self.get_active_provider()
        if not provider:
            raise RuntimeError(f"No active TTS provider configured: {self.active_provider_name}")

        try:
            return await provider.synthesize(text, voice, speed)
        except Exception as e_primary:
            logger.warning(
                "Primary TTS provider '%s' failed (%s). Attempting fallback cascade.",
                provider.name,
                e_primary,
            )
            for name, fallback in self._providers.items():
                if name != provider.name:
                    try:
                        logger.info("Failing over to fallback TTS provider: %s", name)
                        return await fallback.synthesize(text, voice, speed)
                    except Exception as e_fb:
                        logger.debug("Fallback TTS '%s' failed: %s", name, e_fb)

            raise RuntimeError(f"All TTS providers failed. Primary error: {e_primary}")

    async def synthesize_stream(
        self, text: str, voice: Optional[str] = None, speed: float = 1.0
    ):
        """Stream synthesize audio with active provider, falling back if unavailable."""
        provider = self.get_active_provider()
        if not provider:
            raise RuntimeError(f"No active TTS provider configured: {self.active_provider_name}")

        try:
            async for chunk in provider.synthesize_stream(text, voice, speed):
                yield chunk
        except Exception as e_primary:
            logger.warning(
                "Primary TTS provider '%s' failed in stream (%s). Attempting fallback cascade.",
                provider.name,
                e_primary,
            )
            for name, fallback in self._providers.items():
                if name != provider.name:
                    try:
                        logger.info("Failing over to fallback TTS stream provider: %s", name)
                        async for chunk in fallback.synthesize_stream(text, voice, speed):
                            yield chunk
                        return
                    except Exception as e_fb:
                        logger.debug("Fallback TTS '%s' stream failed: %s", name, e_fb)

            raise RuntimeError(f"All TTS stream providers failed. Primary error: {e_primary}")
