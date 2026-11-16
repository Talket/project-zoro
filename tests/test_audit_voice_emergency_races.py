"""Audit tests for Emergency Halt across active voice operations and cancellation races."""

import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.security.emergency import EmergencyManager
from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.manager import VoiceManager
from zoro.voice.models import VoiceState
from zoro.voice.pipeline.voice_pipeline import VoicePipeline
from zoro.voice.stt.mock import MockSTTProvider
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.tts.mock import MockTTSProvider
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.vad.detector import VoiceActivityDetector
from zoro.voice.wake.wake_word import WakeWordDetector


@pytest.mark.asyncio
async def test_emergency_halt_during_active_capture(test_db):
    """Verify emergency halt stops active microphone capture immediately."""
    emergency = EmergencyManager()
    orch = MagicMock()
    voice = VoiceManager(db=test_db, orchestrator=orch, emergency_mgr=emergency)

    # Start capture
    voice.enable()
    assert voice.capture.is_capturing is True

    # Trigger emergency halt
    with patch.object(emergency, "is_halted", return_value=(True, {"reason": "User kill"})):
        assert voice._check_emergency_halt() is True
        assert voice.capture.is_capturing is False
        assert voice.pipeline.state == VoiceState.DISABLED


@pytest.mark.asyncio
async def test_emergency_halt_during_active_playback(test_db):
    """Verify emergency halt stops speaker playback and flushes queued audio."""
    emergency = EmergencyManager()
    orch = MagicMock()
    voice = VoiceManager(db=test_db, orchestrator=orch, emergency_mgr=emergency)

    # Queue multiple audio chunks
    voice.playback._is_playing = True
    voice.playback.play_chunk(b"chunk1" * 100)
    voice.playback.play_chunk(b"chunk2" * 100)
    voice.playback.play_chunk(b"chunk3" * 100)

    # Emergency halt fires
    with patch.object(emergency, "is_halted", return_value=(True, {"reason": "Emergency"})):
        voice._check_emergency_halt()
        assert voice.playback.is_playing is False
        assert voice.playback._queue.qsize() == 0


@pytest.mark.asyncio
async def test_emergency_halt_during_active_stt(test_db):
    """Verify emergency halt prevents pipeline from proceeding with STT result."""
    emergency = EmergencyManager()
    orch = MagicMock()
    voice = VoiceManager(db=test_db, orchestrator=orch, emergency_mgr=emergency)

    # Mock long STT processing
    async def slow_transcribe(*args, **kwargs):
        # Emergency halt occurs during transcription
        with patch.object(emergency, "is_halted", return_value=(True, {"reason": "Kill"})):
            voice._check_emergency_halt()
        raise asyncio.CancelledError("Emergency halt cancelled STT")

    voice.stt.get_active_provider().transcribe = slow_transcribe

    try:
        await voice.pipeline._process_utterance(b"audio_bytes")
    except asyncio.CancelledError:
        pass

    assert voice.pipeline.state in (VoiceState.DISABLED, VoiceState.ERROR, VoiceState.IDLE)


@pytest.mark.asyncio
async def test_cancellation_race_authorization_then_halt(test_db):
    """Test race condition: emergency halt occurs immediately after operation passes authorization check."""
    emergency = EmergencyManager()
    orch = MagicMock()

    # Step 1: Pre-authorization succeeds
    halted_state = [False]

    def dynamic_halt_check():
        return (halted_state[0], {"reason": "Race Kill"} if halted_state[0] else None)

    emergency.is_halted = dynamic_halt_check

    voice = VoiceManager(db=test_db, orchestrator=orch, emergency_mgr=emergency)
    assert voice._check_emergency_halt() is False

    # Step 2: Emergency halt is activated just before dispatch
    halted_state[0] = True

    # Step 3: Re-checking halt must reject execution
    assert voice._check_emergency_halt() is True
    assert voice.enable() is False
    assert voice.trigger_push_to_talk() is False


@pytest.mark.asyncio
async def test_emergency_halt_clears_pending_utterance_frames(test_db):
    """Verify pipeline active utterance buffer is discarded on emergency stop."""
    emergency = EmergencyManager()
    orch = MagicMock()
    voice = VoiceManager(db=test_db, orchestrator=orch, emergency_mgr=emergency)

    voice.enable()
    voice.pipeline._collecting_utterance = True
    voice.pipeline._utterance_frames = [b"frame1", b"frame2", b"frame3"]

    with patch.object(emergency, "is_halted", return_value=(True, {"reason": "Kill"})):
        voice._check_emergency_halt()
        assert len(voice.pipeline._utterance_frames) == 0
        assert voice.pipeline._collecting_utterance is False
