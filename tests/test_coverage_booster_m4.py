"""Comprehensive Coverage Booster Tests for Milestone 04 Voice Subsystem."""

import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.devices import AudioDeviceManager
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.manager import VoiceManager
from zoro.voice.models import STTConfig, TTSConfig, VoiceState
from zoro.voice.monitoring.health import VoiceHealthMonitor
from zoro.voice.monitoring.metrics import VoiceMetricsCollector
from zoro.voice.pipeline.streaming import StreamingTextChunker
from zoro.voice.pipeline.voice_pipeline import VoicePipeline
from zoro.voice.stt.faster_whisper import FasterWhisperProvider
from zoro.voice.stt.mock import MockSTTProvider
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.tts.mock import MockTTSProvider
from zoro.voice.tts.piper import PiperTTSProvider
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.tts.sapi import WindowsSapiTTSProvider
from zoro.voice.vad.detector import VoiceActivityDetector
from zoro.voice.wake.wake_word import WakeWordDetector


def test_streaming_text_chunker():
    """Verify StreamingTextChunker splits token stream into completed sentences."""
    chunker = StreamingTextChunker()

    tokens1 = ["Hello", " world", "! ", "How", " are"]
    sentences1 = []
    for t in tokens1:
        s = chunker.add_token(t)
        sentences1.extend(s)

    assert len(sentences1) == 1
    assert sentences1[0] == "Hello world!"

    tokens2 = [" you", " doing", "? ", "I am", " fine."]
    sentences2 = []
    for t in tokens2:
        s = chunker.add_token(t)
        sentences2.extend(s)

    assert len(sentences2) == 2
    assert "How are you doing?" in sentences2[0]
    assert "I am fine." in sentences2[1]

    # Flush remaining
    chunker.add_token("Extra unclosed thought")
    flushed = chunker.flush()
    assert flushed == "Extra unclosed thought"
    assert chunker.flush() == ""


@pytest.mark.asyncio
async def test_voice_metrics_collector(test_db):
    """Verify VoiceMetricsCollector window trimming and summary calculations."""
    collector = VoiceMetricsCollector(db=test_db)

    # Record 105 metrics to test >100 window pop
    for i in range(105):
        await collector.record_metric("stt_ms", float(i), session_id="vses-test")

    await collector.record_metric("ttft_ms", 50.0)
    await collector.record_metric("tts_ms", 30.0)

    summary = collector.get_summary()
    assert "avg_stt_ms" in summary
    assert "avg_ttft_ms" in summary
    assert summary["avg_ttft_ms"] == 50.0
    assert summary["avg_tts_ms"] == 30.0


def test_audio_health_monitor():
    """Verify VoiceHealthMonitor device presence and system checks."""
    dev_mgr = AudioDeviceManager()
    monitor = VoiceHealthMonitor(device_manager=dev_mgr)

    health = monitor.check_health()
    assert "microphone_available" in health
    assert "speaker_available" in health
    assert "healthy" in health


def test_audio_capture_callback_stereo_and_float_conversion():
    """Verify _audio_callback handles stereo arrays and float32 data."""
    received = []
    cap = AudioCaptureManager(sample_rate=16000, channels=1)
    cap.register_callback(lambda raw, rms: received.append((raw, rms)))

    # Stereo float32 input
    stereo_data = np.zeros((320, 2), dtype=np.float32)
    stereo_data[:, 0] = 0.5
    stereo_data[:, 1] = 0.5

    cap._audio_callback(stereo_data, 320, {}, None)
    assert len(received) == 1
    assert len(received[0][0]) == 640  # 320 samples * 2 bytes
    assert received[0][1] > 0.0


def test_audio_playback_play_complete_audio():
    """Verify play_complete_audio calls stop and play_chunk."""
    pb = AudioPlaybackManager()
    with patch.object(pb, "stop_playback") as mock_stop, patch.object(pb, "play_chunk") as mock_chunk:
        pb.play_complete_audio(b"pcm_data", sample_rate=16000)
        assert mock_stop.called
        assert mock_chunk.called


@pytest.mark.asyncio
async def test_piper_tts_synthesize_and_stream():
    """Verify PiperTTSProvider load and error behavior."""
    piper = PiperTTSProvider()
    assert piper.name == "piper"

    # Without downloaded ONNX model, load returns False and synthesize raises RuntimeError
    with pytest.raises(RuntimeError):
        await piper.synthesize("Testing Piper TTS fallback.")

    # With mocked voice instance
    mock_voice = MagicMock()
    mock_wav = np.zeros(1600, dtype=np.int16).tobytes()
    mock_voice.synthesize_stream_raw.return_value = [mock_wav]

    piper._voice_instance = mock_voice
    piper._is_loaded = True

    pcm = await piper.synthesize("Testing mocked Piper TTS.")
    assert isinstance(pcm, bytes)
    assert len(pcm) > 0

    chunks = []
    async for chunk in piper.synthesize_stream("Testing Piper streaming sentence."):
        chunks.append(chunk)
    assert len(chunks) >= 1

    await piper.unload()
    assert not piper.is_loaded


@pytest.mark.asyncio
async def test_windows_sapi_speed_and_voice_change():
    """Verify WindowsSapiTTSProvider voice listing and speed configuration."""
    sapi = WindowsSapiTTSProvider()
    if not await sapi.health_check():
        pytest.skip("SAPI not supported")

    # Synthesize with custom speed
    pcm = await sapi.synthesize("Speed test.", speed=1.5)
    assert len(pcm) > 0


@pytest.mark.asyncio
async def test_voice_manager_lifecycle_and_helpers(test_db):
    """Verify VoiceManager comprehensive helper methods and toggles."""
    orch = MagicMock()
    orch.process_request = AsyncMock(return_value={"status": "COMPLETED", "response": "OK"})

    mgr = VoiceManager(db=test_db, orchestrator=orch)
    await mgr.initialize()

    # Status
    status = mgr.get_status()
    assert "health" in status
    assert "conversation_id" in status

    # Wake word toggles
    assert mgr.set_wake_word_phrase("zoro", False) is True
    assert mgr.set_wake_word_phrase("zoro", True) is True

    # Device selection
    assert mgr.set_input_device(0) is True
    assert mgr.set_output_device(0) is True

    # Provider selection
    assert await mgr.set_stt_provider("mock") is True
    assert await mgr.set_tts_provider("mock") is True

    # Listening toggles
    assert mgr.stop_listening() is True
    assert mgr.start_listening() is True

    # Push to talk
    assert mgr.trigger_push_to_talk() is True

    # Stop speaking
    assert mgr.stop_speaking() is True

    # Shutdown
    await mgr.shutdown()
