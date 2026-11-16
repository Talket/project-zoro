"""Speech-to-Text (STT) Subsystem."""

from __future__ import annotations

from zoro.voice.stt.base import BaseSTTProvider
from zoro.voice.stt.faster_whisper import FasterWhisperProvider
from zoro.voice.stt.whisper_cpp import WhisperCppProvider
from zoro.voice.stt.mock import MockSTTProvider
from zoro.voice.stt.registry import STTRegistry

__all__ = [
    "BaseSTTProvider",
    "FasterWhisperProvider",
    "WhisperCppProvider",
    "MockSTTProvider",
    "STTRegistry",
]
