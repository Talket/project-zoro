"""Text-to-Speech (TTS) Subsystem."""

from __future__ import annotations

from zoro.voice.tts.base import BaseTTSProvider
from zoro.voice.tts.piper import PiperTTSProvider
from zoro.voice.tts.sapi import WindowsSapiTTSProvider
from zoro.voice.tts.mock import MockTTSProvider
from zoro.voice.tts.registry import TTSRegistry

__all__ = [
    "BaseTTSProvider",
    "PiperTTSProvider",
    "WindowsSapiTTSProvider",
    "MockTTSProvider",
    "TTSRegistry",
]
