"""Unit and integration tests for VoicePipeline and streaming state transitions."""

import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.interruption import InterruptionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.models import STTResult, VoiceState
from zoro.voice.pipeline.voice_pipeline import VoicePipeline
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.vad.detector import VoiceActivityDetector
from zoro.voice.wake.wake_word import WakeWordDetector


@pytest.fixture
def mock_pipeline_deps():
    capture = MagicMock(spec=AudioCaptureManager)
    capture.audio_buffer = MagicMock()
    capture.audio_buffer.get_recent.return_value = np.zeros(1600, dtype=np.int16)
    capture.current_rms = 0.05

    playback = MagicMock(spec=AudioPlaybackManager)
    playback.is_playing = False

    vad = MagicMock(spec=VoiceActivityDetector)
    vad_res = MagicMock()
    vad_res.is_speech = False
    vad_res.speech_onset = False
    vad_res.speech_ended = False
    vad.process_frame.return_value = vad_res

    wake = MagicMock(spec=WakeWordDetector)
    wake_res = MagicMock()
    wake_res.detected = False
    wake.process_audio.return_value = wake_res
    wake_ptt = MagicMock()
    wake_ptt.detected = True
    wake_ptt.wake_word = "push_to_talk"
    wake.trigger_push_to_talk.return_value = wake_ptt

    stt = MagicMock(spec=STTRegistry)
    stt.transcribe = AsyncMock(return_value=STTResult(transcript="Hello Zoro", confidence=0.95))

    turn_mgr = MagicMock(spec=VoiceTurnManager)
    turn_mgr.execute_turn = AsyncMock(return_value="Greetings, how may I assist you?")

    interruption = MagicMock(spec=InterruptionManager)
    interruption.check_audio_frame.return_value = False

    return {
        "capture": capture,
        "playback": playback,
        "vad": vad,
        "wake": wake,
        "stt": stt,
        "turn_mgr": turn_mgr,
        "interruption": interruption,
    }


def test_pipeline_enable_disable(mock_pipeline_deps):
    """Verify VoicePipeline enable, disable, and listening state transitions."""
    states = []
    pipeline = VoicePipeline(
        capture=mock_pipeline_deps["capture"],
        playback=mock_pipeline_deps["playback"],
        vad=mock_pipeline_deps["vad"],
        wake=mock_pipeline_deps["wake"],
        stt=mock_pipeline_deps["stt"],
        turn_manager=mock_pipeline_deps["turn_mgr"],
        interruption=mock_pipeline_deps["interruption"],
        on_state_change=lambda s: states.append(s),
    )

    assert pipeline.state == VoiceState.IDLE
    assert not pipeline.is_enabled

    # Enable
    pipeline.enable()
    assert pipeline.is_enabled is True
    assert pipeline.state == VoiceState.LISTENING
    assert mock_pipeline_deps["capture"].start_capture.called

    # Toggle listening
    pipeline.set_listening(False)
    assert pipeline.state == VoiceState.IDLE

    pipeline.set_listening(True)
    assert pipeline.state == VoiceState.LISTENING

    # Disable
    pipeline.disable()
    assert pipeline.is_enabled is False
    assert pipeline.state == VoiceState.DISABLED
    assert mock_pipeline_deps["capture"].stop_capture.called
    assert mock_pipeline_deps["playback"].stop_playback.called


def test_pipeline_push_to_talk(mock_pipeline_deps):
    """Verify Push-to-Talk transitions pipeline to WAKE_DETECTED and collects utterance."""
    pipeline = VoicePipeline(
        capture=mock_pipeline_deps["capture"],
        playback=mock_pipeline_deps["playback"],
        vad=mock_pipeline_deps["vad"],
        wake=mock_pipeline_deps["wake"],
        stt=mock_pipeline_deps["stt"],
        turn_manager=mock_pipeline_deps["turn_mgr"],
        interruption=mock_pipeline_deps["interruption"],
    )

    pipeline.trigger_push_to_talk()
    assert pipeline.is_enabled is True
    assert pipeline.state == VoiceState.WAKE_DETECTED
    assert pipeline._collecting_utterance is True


@pytest.mark.asyncio
async def test_pipeline_process_utterance(mock_pipeline_deps):
    """Verify utterance processing flow through STT and turn manager."""
    pipeline = VoicePipeline(
        capture=mock_pipeline_deps["capture"],
        playback=mock_pipeline_deps["playback"],
        vad=mock_pipeline_deps["vad"],
        wake=mock_pipeline_deps["wake"],
        stt=mock_pipeline_deps["stt"],
        turn_manager=mock_pipeline_deps["turn_mgr"],
        interruption=mock_pipeline_deps["interruption"],
    )
    pipeline.enable()

    dummy_audio = np.zeros(16000, dtype=np.int16).tobytes()
    await pipeline._process_utterance(dummy_audio)

    assert mock_pipeline_deps["stt"].transcribe.called
    assert mock_pipeline_deps["turn_mgr"].execute_turn.called
    assert pipeline.metrics.total_turnaround_ms > 0.0


def test_pipeline_interruption_and_playback_finished(mock_pipeline_deps):
    """Verify barge-in interruption and playback completion return pipeline to listening."""
    pipeline = VoicePipeline(
        capture=mock_pipeline_deps["capture"],
        playback=mock_pipeline_deps["playback"],
        vad=mock_pipeline_deps["vad"],
        wake=mock_pipeline_deps["wake"],
        stt=mock_pipeline_deps["stt"],
        turn_manager=mock_pipeline_deps["turn_mgr"],
        interruption=mock_pipeline_deps["interruption"],
    )
    pipeline.enable()

    # Interruption
    pipeline._on_interrupted("barge_in")
    assert pipeline.state == VoiceState.INTERRUPTED
    assert pipeline._collecting_utterance is False

    # When speaking completes -> transitions back to listening
    pipeline.set_state(VoiceState.SPEAKING)
    pipeline._on_playback_finished()
    assert pipeline.state == VoiceState.LISTENING
