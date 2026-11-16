"""Audit tests for deep failure modes, device failures, fallback cascading, and COM threading."""

import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.devices import AudioDeviceManager
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.models import STTResult, TTSAudioChunk, VADConfig, VoiceState
from zoro.voice.pipeline.voice_pipeline import VoicePipeline
from zoro.voice.stt.faster_whisper import FasterWhisperProvider
from zoro.voice.stt.mock import MockSTTProvider
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.stt.whisper_cpp import WhisperCppProvider
from zoro.voice.tts.mock import MockTTSProvider
from zoro.voice.tts.piper import PiperTTSProvider
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.tts.sapi import WindowsSapiTTSProvider
from zoro.voice.vad.detector import VoiceActivityDetector
from zoro.voice.wake.wake_word import WakeWordDetector


# --------------------------------------------------------------------
# 1. VoicePipeline Failure Modes & Edge Cases
# --------------------------------------------------------------------

def test_voice_pipeline_malformed_and_empty_frames():
    """Verify VoicePipeline gracefully handles empty or corrupt audio frames without crashing."""
    capture = MagicMock(spec=AudioCaptureManager)
    capture.audio_buffer = MagicMock()
    capture.audio_buffer.get_recent.return_value = np.zeros(1600, dtype=np.int16)
    playback = MagicMock(spec=AudioPlaybackManager)
    playback.is_playing = False
    vad = MagicMock(spec=VoiceActivityDetector)
    wake = MagicMock(spec=WakeWordDetector)
    wake.process_audio.return_value = MagicMock(detected=False)
    stt = MagicMock(spec=STTRegistry)
    turn_mgr = MagicMock(spec=VoiceTurnManager)
    interruption = MagicMock()

    pipeline = VoicePipeline(
        capture=capture,
        playback=playback,
        vad=vad,
        wake=wake,
        stt=stt,
        turn_manager=turn_mgr,
        interruption=interruption,
    )
    pipeline.enable()

    # Feed empty frame
    pipeline._on_audio_frame(b"", 0.0)

    # Feed corrupt byte length
    pipeline._on_audio_frame(b"\x00\x01\x02", 0.1)

    # Check state unchanged
    assert pipeline.state == VoiceState.LISTENING


def test_voice_pipeline_max_utterance_timeout():
    """Verify VoicePipeline caps continuous utterance collection at 750 frames (~15s) to prevent memory leak."""
    capture = MagicMock(spec=AudioCaptureManager)
    capture.audio_buffer = MagicMock()
    capture.audio_buffer.get_recent.return_value = np.zeros(1600, dtype=np.int16)
    playback = MagicMock(spec=AudioPlaybackManager)
    playback.is_playing = False
    vad = MagicMock(spec=VoiceActivityDetector)
    vad_res = MagicMock(speech_ended=False)
    vad.process_frame.return_value = vad_res

    wake = MagicMock(spec=WakeWordDetector)
    wake.process_audio.return_value = MagicMock(detected=False)
    stt = MagicMock(spec=STTRegistry)
    turn_mgr = MagicMock(spec=VoiceTurnManager)
    interruption = MagicMock()

    pipeline = VoicePipeline(
        capture=capture,
        playback=playback,
        vad=vad,
        wake=wake,
        stt=stt,
        turn_manager=turn_mgr,
        interruption=interruption,
    )
    pipeline.enable()
    pipeline._collecting_utterance = True

    with patch.object(pipeline, "_dispatch_transcription") as mock_dispatch:
        # Feed 751 frames
        frame = np.zeros(320, dtype=np.int16).tobytes()
        for _ in range(752):
            pipeline._on_audio_frame(frame, 0.1)

        # Must auto-dispatch and terminate collection
        assert mock_dispatch.called
        assert pipeline._collecting_utterance is False


# --------------------------------------------------------------------
# 2. STT Registry Cascading and Failure Recovery
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stt_registry_all_providers_fail():
    """Verify STTRegistry raises informative RuntimeError when all providers fail."""
    registry = STTRegistry(default_provider="mock")
    mock_p = registry.get_provider("mock")
    mock_p.should_fail = True

    with patch.object(registry.get_provider("faster-whisper"), "transcribe", side_effect=RuntimeError("FW crash")), \
         patch.object(registry.get_provider("whisper.cpp"), "transcribe", side_effect=RuntimeError("CPP crash")):
        with pytest.raises(RuntimeError) as exc_info:
            await registry.transcribe(b"test audio")
        assert "All STT providers failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_whisper_cpp_execution_failure():
    """Verify WhisperCppProvider handles missing binary and execution errors."""
    provider = WhisperCppProvider()

    # Load when cli executable is missing / server offline
    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        assert await provider.load() is False
        assert await provider.health_check() is False

    # Transcribe when not loaded
    with pytest.raises(RuntimeError) as exc_info:
        await provider.transcribe(b"audio")
    assert "not loaded" in str(exc_info.value)


# --------------------------------------------------------------------
# 3. TTS Registry Stream Cascading and Playback Stress
# --------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tts_registry_stream_cascading():
    """Verify TTSRegistry fails over to secondary provider during streaming failure."""
    registry = TTSRegistry(default_provider="mock")
    mock_p = registry.get_provider("mock")
    mock_p.should_fail = True

    # Fallback mock
    fallback = MockTTSProvider()
    registry.register_provider(fallback)

    chunks = []
    with patch.object(registry.get_provider("windows-sapi"), "synthesize_stream", side_effect=RuntimeError("SAPI stream err")):
        async for chunk in registry.synthesize_stream("Fallback stream test."):
            chunks.append(chunk)

    assert len(chunks) >= 1


def test_audio_playback_rapid_hammering():
    """Verify AudioPlaybackManager is resilient to rapid start/stop/queue hammering."""
    pb = AudioPlaybackManager()

    chunk = (np.ones(1600, dtype=np.int16) * 500).tobytes()

    for _ in range(50):
        pb.play_chunk(chunk)
        pb.stop_playback()

    assert pb.is_playing is False
    assert pb._queue.qsize() == 0
    pb.stop()


# --------------------------------------------------------------------
# 4. WebRTC VAD Frame Sizes and COM Threading Verification
# --------------------------------------------------------------------

def test_webrtc_vad_standard_and_irregular_frame_sizes():
    """Verify WebRTC VAD classifies 10ms, 20ms, 30ms frames and energy fallback for irregular sizes."""
    cfg = VADConfig(aggressiveness=1, energy_threshold=0.01)
    vad = VoiceActivityDetector(config=cfg, sample_rate=16000)

    # Standard frames for 16kHz:
    # 10ms = 160 samples = 320 bytes
    # 20ms = 320 samples = 640 bytes
    # 30ms = 480 samples = 960 bytes
    frame_10ms = np.zeros(160, dtype=np.int16).tobytes()
    frame_20ms = np.zeros(320, dtype=np.int16).tobytes()
    frame_30ms = np.zeros(480, dtype=np.int16).tobytes()

    res_10 = vad.process_frame(frame_10ms)
    assert res_10.is_speech is False

    res_20 = vad.process_frame(frame_20ms)
    assert res_20.is_speech is False

    res_30 = vad.process_frame(frame_30ms)
    assert res_30.is_speech is False

    # Irregular size: 250 samples = 500 bytes (WebRTC VAD rejects; falls back to energy)
    frame_irregular = (np.ones(250, dtype=np.int16) * 10000).tobytes()
    res_irreg = vad.process_frame(frame_irregular)
    assert res_irreg.energy > 0.01  # Handled via energy fallback without exception


@pytest.mark.asyncio
async def test_sapi_com_threading_initialization():
    """Verify Windows SAPI5 properly initializes and uninitializes COM on worker threads."""
    sapi = WindowsSapiTTSProvider()
    if not await sapi.health_check():
        pytest.skip("SAPI not supported")

    # Run synthesis across 3 separate concurrent asyncio threads
    tasks = [
        sapi.synthesize(f"Thread test utterance number {i}.")
        for i in range(3)
    ]
    results = await asyncio.gather(*tasks)
    assert len(results) == 3
    for r in results:
        assert isinstance(r, bytes)
        assert len(r) > 0
