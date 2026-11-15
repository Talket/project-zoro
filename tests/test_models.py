"""Tests for Model Provider abstraction and MockModelProvider."""

import pytest
from zoro.models.base import ChatCompletionRequest, ModelCapabilities, ProviderHealth
from zoro.models.mock import MockModelProvider


@pytest.mark.asyncio
async def test_mock_model_provider_chat_completion():
    provider = MockModelProvider(default_response="ZORO online.")
    req = ChatCompletionRequest(
        model="mock-v1",
        messages=[{"role": "user", "content": "Hello"}],
    )
    resp = await provider.chat_completion(req)
    assert resp.content == "ZORO online."
    assert resp.model == "mock-v1"
    assert resp.usage["total_tokens"] > 0


@pytest.mark.asyncio
async def test_mock_model_provider_health_and_capabilities():
    provider = MockModelProvider()
    health = await provider.health_check()
    assert health.is_available is True
    assert health.provider_name == "MockModelProvider"

    caps = await provider.get_capabilities("mock-v1")
    assert caps.model_name == "mock-v1"
    assert caps.context_window == 4096
    assert caps.supports_tools is True
