"""Native Windows SAPI5 Text-to-Speech Provider."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, List, Optional
import win32com.client
import pythoncom

from zoro.voice.models import TTSAudioChunk, TTSConfig
from zoro.voice.tts.base import BaseTTSProvider

logger = logging.getLogger(__name__)


class WindowsSapiTTSProvider(BaseTTSProvider):
    """100% offline, zero-dependency native Windows Speech API (SAPI5) synthesizer."""

    def __init__(self, config: Optional[TTSConfig] = None) -> None:
        super().__init__(config)

    @property
    def name(self) -> str:
        return "windows-sapi"

    async def load(self) -> bool:
        self._is_loaded = await self.health_check()
        return self._is_loaded

    async def unload(self) -> None:
        self._is_loaded = False

    async def health_check(self) -> bool:
        def _check():
            try:
                pythoncom.CoInitialize()
                try:
                    voice = win32com.client.Dispatch("SAPI.SpVoice")
                    return voice is not None
                finally:
                    pythoncom.CoUninitialize()
            except Exception:
                return False
        return await asyncio.to_thread(_check)

    async def list_voices(self) -> List[str]:
        def _get_voices():
            pythoncom.CoInitialize()
            try:
                voice = win32com.client.Dispatch("SAPI.SpVoice")
                voices = []
                for v in voice.GetVoices():
                    desc = v.GetDescription()
                    voices.append(desc)
                return voices
            except Exception as e:
                logger.error("Failed to list SAPI voices: %s", e)
                return ["Microsoft David Desktop", "Microsoft Zira Desktop"]
            finally:
                pythoncom.CoUninitialize()

        return await asyncio.to_thread(_get_voices)

    async def synthesize(self, text: str, voice: Optional[str] = None, speed: float = 1.0) -> bytes:
        if not text.strip():
            return b""

        def _sync_speak() -> bytes:
            pythoncom.CoInitialize()
            try:
                sp_voice = win32com.client.Dispatch("SAPI.SpVoice")
                sp_stream = win32com.client.Dispatch("SAPI.SpMemoryStream")

                # SAFT22kHz16BitMono = 22, SAFT16kHz16BitMono = 18
                sp_stream.Format.Type = 22
                sp_voice.AudioOutputStream = sp_stream

                # Configure voice if requested
                selected_voice = voice or self.config.voice
                if selected_voice and selected_voice != "default":
                    for v in sp_voice.GetVoices():
                        if selected_voice.lower() in v.GetDescription().lower():
                            sp_voice.Voice = v
                            break

                # Configure rate: speed 1.0 -> 0, range is -10 to 10
                rate = int((speed - 1.0) * 10.0)
                sp_voice.Rate = max(-10, min(10, rate))

                # Volume: 0 to 100
                sp_voice.Volume = int(self.config.volume * 100.0)

                sp_voice.Speak(text)
                return bytes(sp_stream.GetData())
            finally:
                pythoncom.CoUninitialize()

        return await asyncio.to_thread(_sync_speak)

    async def synthesize_stream(
        self, text: str, voice: Optional[str] = None, speed: float = 1.0
    ) -> AsyncIterator[TTSAudioChunk]:
        """Stream sentence-level audio chunks."""
        # For SAPI, synthesize the phrase and yield as chunk
        pcm = await self.synthesize(text, voice, speed)
        duration_ms = (len(pcm) / (22050 * 2)) * 1000.0
        yield TTSAudioChunk(
            pcm_bytes=pcm,
            sample_rate=22050,
            duration_ms=duration_ms,
            is_final=True,
        )
