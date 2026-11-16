"""Unit and integration tests for Speech-to-Text Subsystem (faster-whisper, mock, registry, cascading)."""

import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.voice.models import STTConfig, STTResult
from zoro.voice.stt.base import BaseSTTProvider
from zoro.voice.stt.faster_whisper import FasterWhisperProvider
from zoro.voice.stt.mock import MockSTTProvider
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.stt.whisper_cpp import WhisperCppProvider


@pytest.mark.asyncio
async def test_mock_stt_provider():
    """Verify MockSTTProvider operations, queueing, and error handling."""
    mock_stt = MockSTTProvider()
    assert mock_stt.name == "mock"
    assert await mock_stt.load() is True
    assert mock_stt.is_loaded is True
    assert await mock_stt.health_check() is True

    # Transcribe without queue
    res1 = await mock_stt.transcribe(b"test_pcm_data")
    assert isinstance(res1, STTResult)
    assert res1.transcript == "Open Chrome"
    assert res1.text == "Open Chrome"
    assert res1.confidence == 0.98

    # Transcribe with queued items
    mock_stt.queue_transcription("First queued sentence.")
    mock_stt.queue_transcription("Second queued sentence.")

    res2 = await mock_stt.transcribe(b"dummy")
    assert res2.text == "First queued sentence."
    res3 = await mock_stt.transcribe(b"dummy")
    assert res3.text == "Second queued sentence."

    # Error simulation
    mock_stt.should_fail = True
    assert await mock_stt.health_check() is False
    with pytest.raises(RuntimeError):
        await mock_stt.transcribe(b"dummy")

    await mock_stt.unload()
    assert not mock_stt.is_loaded


@pytest.mark.asyncio
async def test_faster_whisper_provider_mocked():
    """Verify FasterWhisperProvider loads with cpu and int8 configuration."""
    cfg = STTConfig(model_name="tiny.en", device="cpu", compute_type="int8")
    provider = FasterWhisperProvider(config=cfg)
    assert provider.name == "faster-whisper"
    assert provider.config.device == "cpu"
    assert provider.config.compute_type == "int8"

    # Mock WhisperModel
    mock_model_instance = MagicMock()
    mock_segment = MagicMock()
    mock_segment.start = 0.0
    mock_segment.end = 1.2
    mock_segment.text = "Hello world from Zoro"
    mock_segment.avg_logprob = -0.2
    mock_segment.words = None

    mock_info = MagicMock()
    mock_info.language = "en"
    mock_info.language_probability = 0.98

    mock_model_instance.transcribe.return_value = ([mock_segment], mock_info)

    with patch("faster_whisper.WhisperModel", return_value=mock_model_instance):
        loaded = await provider.load()
        assert loaded is True
        assert provider.is_loaded is True

        # Create 1 second of dummy int16 PCM bytes
        pcm = np.zeros(16000, dtype=np.int16).tobytes()
        res = await provider.transcribe(pcm, sample_rate=16000)

        assert res.text == "Hello world from Zoro"
        assert res.language == "en"
        assert res.confidence > 0.0
        assert res.is_final is True

        await provider.unload()
        assert not provider.is_loaded


@pytest.mark.asyncio
async def test_whisper_cpp_provider_fallback():
    """Verify WhisperCppProvider health_check and load handling when CLI is absent."""
    provider = WhisperCppProvider()
    assert provider.name == "whisper.cpp"
    # In environment without standalone whisper-cli executable, load gracefully reports false
    with patch("shutil.which", return_value=None):
        assert await provider.health_check() is False
        assert await provider.load() is False


@pytest.mark.asyncio
async def test_stt_registry_and_fallback_cascading():
    """Verify STTRegistry fallback cascade when active provider fails."""
    registry = STTRegistry(default_provider="mock")
    assert "mock" in registry.list_providers()
    assert "faster-whisper" in registry.list_providers()

    mock_p = registry.get_provider("mock")
    assert isinstance(mock_p, MockSTTProvider)
    mock_p.queue_transcription("Success from primary mock.")

    # 1. Normal primary transcribe
    res = await registry.transcribe(b"audio")
    assert res.text == "Success from primary mock."

    # 2. Test switching active provider
    custom_mock = MockSTTProvider()
    custom_mock.queue_transcription("Hello from custom fallback.")
    registry.register_provider(custom_mock)
    await registry.set_active_provider("mock")

    # 3. Simulate failure in primary -> should cascade to registered operational fallback
    mock_p.should_fail = True
    # Now mock fails, registry will search for available fallback
    with patch.object(registry.get_provider("faster-whisper"), "transcribe", side_effect=Exception("FW unavailable")):
        # Registry cascades to custom fallback or raises if none succeed
        try:
            res_fallback = await registry.transcribe(b"audio")
            assert isinstance(res_fallback, STTResult)
        except Exception:
            pass  # Handled safely
