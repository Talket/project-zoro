"""Pydantic data models for PROJECT ZORO Voice Interaction Subsystem."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class VoiceState(str, Enum):
    """Voice Subsystem State Machine states."""
    DISABLED = "DISABLED"
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    WAKE_DETECTED = "WAKE_DETECTED"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


class AudioDevice(BaseModel):
    """Audio input or output device details."""
    index: int
    name: str
    channels: int
    sample_rate: float
    is_input: bool
    is_default: bool = False
    api: str = "MME"


class AudioBufferConfig(BaseModel):
    """Audio buffering configuration."""
    sample_rate: int = 16000
    channels: int = 1
    chunk_size_samples: int = 320  # 20ms at 16kHz
    max_buffer_seconds: float = 30.0


class VADConfig(BaseModel):
    """Voice Activity Detection configuration."""
    aggressiveness: int = 2  # 0 to 3 for WebRTC VAD
    silence_duration_threshold_sec: float = 0.8
    speech_onset_threshold_sec: float = 0.1
    energy_threshold: float = 0.01


class VADResult(BaseModel):
    """Result of Voice Activity Detection analysis."""
    is_speech: bool
    confidence: float = 1.0
    speech_onset: bool = False
    speech_ended: bool = False
    energy: float = 0.0


class WakeWordConfig(BaseModel):
    """Wake word configuration with multi-phrase support."""
    enabled_phrases: List[str] = Field(default_factory=lambda: ["zoro", "hey zoro"])
    sensitivity: float = 0.6
    cooldown_seconds: float = 1.5


class WakeWordResult(BaseModel):
    """Wake-word detection outcome."""
    detected: bool = False
    wake_word: Optional[str] = None
    confidence: float = 0.0
    timestamp: float = 0.0


class STTConfig(BaseModel):
    """Speech-to-text configuration."""
    model_name: str = "base"
    language: Optional[str] = "en"
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 1


class STTResult(BaseModel):
    """Speech-to-text recognition result."""
    transcript: str
    confidence: float = 1.0
    duration_ms: float = 0.0
    language: str = "en"
    is_final: bool = True
    words: List[Dict[str, Any]] = Field(default_factory=list)

    @property
    def text(self) -> str:
        """Convenience alias for transcript."""
        return self.transcript


class TTSConfig(BaseModel):
    """Text-to-speech configuration."""
    voice: str = "default"
    speed: float = 1.0
    volume: float = 1.0
    sample_rate: int = 22050


class TTSAudioChunk(BaseModel):
    """Synthesized PCM audio chunk."""
    pcm_bytes: bytes
    sample_rate: int = 22050
    duration_ms: float = 0.0
    is_final: bool = False


class VoiceSession(BaseModel):
    """Active or archived voice interaction session."""
    session_id: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    status: str = "ACTIVE"
    input_device: Optional[str] = None
    output_device: Optional[str] = None
    stt_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    error: Optional[str] = None


class VoiceUtterance(BaseModel):
    """Recorded voice utterance metadata."""
    id: str
    session_id: str
    conversation_id: Optional[str] = None
    message_id: Optional[str] = None
    transcript: str
    language: str = "en"
    recognition_duration_ms: float = 0.0
    processing_status: str = "RECOGNIZED"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PipelineMetrics(BaseModel):
    """Real-time latency metrics for voice pipeline."""
    wake_latency_ms: float = 0.0
    vad_latency_ms: float = 0.0
    stt_latency_ms: float = 0.0
    ttft_ms: float = 0.0
    tts_latency_ms: float = 0.0
    total_turnaround_ms: float = 0.0
