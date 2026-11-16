"""Voice Subsystem Event Definitions for PROJECT ZORO EventBus."""

from __future__ import annotations

VOICE_STATE_CHANGED = "voice.state_changed"
VOICE_WAKE_DETECTED = "voice.wake_detected"
VOICE_SPEECH_STARTED = "voice.speech_started"
VOICE_SPEECH_ENDED = "voice.speech_ended"
VOICE_TRANSCRIPTION = "voice.transcription"
VOICE_SPEAKING_STARTED = "voice.speaking_started"
VOICE_SPEAKING_CHUNK = "voice.speaking_chunk"
VOICE_SPEAKING_FINISHED = "voice.speaking_finished"
VOICE_INTERRUPTED = "voice.interrupted"
VOICE_ERROR = "voice.error"
VOICE_DEVICE_CHANGED = "voice.device_changed"
