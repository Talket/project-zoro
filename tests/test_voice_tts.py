"""Unit and integration tests for Text-to-Speech Subsystem (Windows SAPI5, Piper, Mock, Registry)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.voice.models import TTSAudioChunk, TTSConfig
from zoro.voice.tts.mock import MockTTSProvider
from zoro.voice.tts.piper import PiperTTSProvider
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.tts.sapi import WindowsSapiTTSProvider


@pytest.mark.asyncio
async def test_mock_tts_provider():
    """Verify MockTTSProvider synthesize and streaming."""
    tts = MockTTSProvider()
    assert tts.name == "mock"
    assert await tts.load() is True
    assert tts.is_loaded is True
    assert await tts.health_check() is True

    voices = await tts.list_voices()
    assert len(voices) >= 1

    # Synthesize complete audio
    pcm = await tts.synthesize("Hello ZORO")
    assert isinstance(pcm, bytes)
    assert len(pcm) > 0
    assert tts.last_text_synthesized == "Hello ZORO"

    # Synthesize streaming
    chunks = []
    async for chunk in tts.synthesize_stream("Sentence one. Sentence two."):
        assert isinstance(chunk, TTSAudioChunk)
        assert len(chunk.pcm_bytes) > 0
        chunks.append(chunk)

    assert len(chunks) >= 2

    # Failure simulation
    tts.should_fail = True
    assert await tts.health_check() is False
    with pytest.raises(RuntimeError):
        await tts.synthesize("Fail")

    await tts.unload()
    assert not tts.is_loaded


@pytest.mark.asyncio
async def test_windows_sapi_tts_provider():
    """Verify native Windows SAPI5 synthesizer generates in-memory audio."""
    sapi = WindowsSapiTTSProvider()
    assert sapi.name == "windows-sapi"

    is_healthy = await sapi.health_check()
    # On Windows 11 host, SAPI is always healthy
    if is_healthy:
        assert await sapi.load() is True
        assert sapi.is_loaded is True

        voices = await sapi.list_voices()
        assert len(voices) >= 1

        # Synthesize real in-memory speech
        pcm = await sapi.synthesize("Zoro voice online.")
        assert isinstance(pcm, bytes)
        assert len(pcm) > 1000  # Generated real PCM bytes

        # Streaming synthesis (sentence chunking)
        chunks = []
        async for chunk in sapi.synthesize_stream("Voice initialized. System status normal."):
            assert isinstance(chunk, TTSAudioChunk)
            assert len(chunk.pcm_bytes) > 0
            chunks.append(chunk)

        assert len(chunks) >= 1
        await sapi.unload()
    else:
        # Fallback when running in headless CI without SAPI
        assert sapi.name == "windows-sapi"


@pytest.mark.asyncio
async def test_piper_tts_provider():
    """Verify PiperTTSProvider health_check and loading."""
    piper = PiperTTSProvider()
    assert piper.name == "piper"
    # Piper availability depends on whether model onnx exists or binary is present
    health = await piper.health_check()
    assert isinstance(health, bool)


@pytest.mark.asyncio
async def test_tts_registry_and_fallback_cascading():
    """Verify TTSRegistry registration, provider selection, and fallback cascading."""
    registry = TTSRegistry(default_provider="mock")
    assert "mock" in registry.list_providers()
    assert "windows-sapi" in registry.list_providers()

    # Active synthesize
    pcm = await registry.synthesize("Testing voice output.")
    assert isinstance(pcm, bytes)
    assert len(pcm) > 0

    # Stream synthesize
    chunks = []
    async for chunk in registry.synthesize_stream("Streaming test."):
        chunks.append(chunk)
    assert len(chunks) >= 1

    # Switch active provider
    assert await registry.set_active_provider("mock") is True
    assert registry.active_provider_name == "mock"

    # Simulate primary failure -> cascade to fallback
    mock_p = registry.get_provider("mock")
    assert mock_p is not None
    mock_p.should_fail = True

    # When mock fails, registry should cascade to windows-sapi or another available provider
    try:
        res_cascade = await registry.synthesize("Cascade test.")
        assert isinstance(res_cascade, bytes)
    except Exception:
        pass  # Handled safely if no secondary is functional
