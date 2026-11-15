"""Tests for AI Model Provider abstraction, adapters, and registry."""

import json
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.models.base import (
    ChatMessage,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionChunk,
    ModelCapabilities,
    ModelInfo,
    ProviderHealth,
)
from zoro.models.exceptions import (
    AuthenticationError,
    CapabilityNotSupportedError,
    ContextLengthExceededError,
    ModelNotFoundError,
    ModelProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from zoro.models.mock import MockModelProvider
from zoro.models.ollama import OllamaProvider
from zoro.models.llama_cpp import LlamaCppProvider
from zoro.models.registry import ProviderRegistry


@pytest.mark.asyncio
async def test_mock_provider_basic_and_streaming():
    mock = MockModelProvider(default_response="Mock answer.")
    health = await mock.health_check()
    assert health.is_available is True
    assert health.provider_name == "MockModelProvider"

    caps = await mock.get_capabilities("mock-model")
    assert caps.supports_tools is True
    assert caps.supports_json_schema is True

    models = await mock.list_models()
    assert len(models) >= 1
    assert models[0].name == "mock-v1"

    # Chat completion
    req = ChatCompletionRequest(
        model="mock-v1",
        messages=[ChatMessage(role="user", content="Hello ZORO")]
    )
    resp = await mock.chat_completion(req)
    assert resp.content == "Mock answer."
    assert resp.usage.get("total_tokens") == 25

    # Enqueued response
    mock.enqueue_response(ChatCompletionResponse(
        id="custom-1",
        model="mock-v1",
        content="Custom enqueued response",
        usage={"total_tokens": 10}
    ))
    resp2 = await mock.chat_completion(req)
    assert resp2.content == "Custom enqueued response"

    # Streaming
    chunks = []
    async for chunk in mock.chat_completion_stream(req):
        if chunk.delta_content:
            chunks.append(chunk.delta_content)
    assert "".join(chunks) == "Mock answer."


@pytest.mark.asyncio
async def test_mock_provider_json_format():
    mock = MockModelProvider()
    req = ChatCompletionRequest(
        model="mock-v1",
        messages=[ChatMessage(role="user", content="JSON please")],
        response_format={"type": "json_object"}
    )
    resp = await mock.chat_completion(req)
    data = json.loads(resp.content)
    assert data.get("status") == "success"


@pytest.mark.asyncio
async def test_ollama_provider_health_and_models():
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")

    # Mock health check
    mock_client = AsyncMock()
    mock_resp = MagicMock(status_code=200)
    mock_resp.json.return_value = {"version": "0.3.14"}
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch.object(provider, "_get_client", return_value=mock_client):
        health = await provider.health_check()
        assert health.is_available is True
        assert health.provider_name == "Ollama"

    # Mock list_models
    tags_resp = MagicMock(status_code=200)
    tags_resp.json.return_value = {
        "models": [
            {
                "name": "qwen2.5:3b",
                "size": 1900000000,
                "modified_at": "2026-01-01T00:00:00Z",
                "details": {
                    "family": "qwen2",
                    "parameter_size": "3B",
                    "quantization_level": "Q4_K_M"
                }
            }
        ]
    }
    mock_client.get.return_value = tags_resp
    with patch.object(provider, "_get_client", return_value=mock_client):
        models = await provider.list_models()
        assert len(models) == 1
        assert models[0].name == "qwen2.5:3b"
        assert models[0].parameter_size == "3B"


@pytest.mark.asyncio
async def test_ollama_provider_chat_completion_and_errors():
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")
    req = ChatCompletionRequest(
        model="qwen2.5:3b",
        messages=[ChatMessage(role="user", content="Test prompt")]
    )

    mock_client = AsyncMock()
    chat_resp = MagicMock(status_code=200)
    chat_resp.json.return_value = {
        "message": {"role": "assistant", "content": "Ollama response"},
        "eval_count": 10,
        "prompt_eval_count": 5,
        "done": True
    }
    mock_client.post.return_value = chat_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch.object(provider, "_get_client", return_value=mock_client):
        res = await provider.chat_completion(req)
        assert res.content == "Ollama response"
        assert res.usage["completion_tokens"] == 10

    # 404 Model Not Found Error
    err_resp = MagicMock(status_code=404, text="model not found")
    mock_client.post.return_value = err_resp
    with patch.object(provider, "_get_client", return_value=mock_client):
        with pytest.raises(ModelNotFoundError):
            await provider.chat_completion(req)


@pytest.mark.asyncio
async def test_llama_cpp_provider_chat_and_capabilities():
    provider = LlamaCppProvider(base_url="http://127.0.0.1:8080")
    req = ChatCompletionRequest(
        model="default",
        messages=[ChatMessage(role="user", content="Hello from llama.cpp")]
    )

    mock_client = AsyncMock()
    chat_resp = MagicMock(status_code=200)
    chat_resp.json.return_value = {
        "id": "chatcmpl-test",
        "choices": [{"message": {"role": "assistant", "content": "Local cpp output"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 8, "completion_tokens": 12, "total_tokens": 20}
    }
    mock_client.post.return_value = chat_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch.object(provider, "_get_client", return_value=mock_client):
        res = await provider.chat_completion(req)
        assert res.content == "Local cpp output"
        assert res.usage["total_tokens"] == 20

    # Test capabilities
    caps = await provider.get_capabilities("default")
    assert caps.supports_tools is True
    assert caps.supports_json_schema is True


@pytest.mark.asyncio
async def test_provider_registry_coordination_and_fallback():
    registry = ProviderRegistry()
    mock1 = MockModelProvider(default_response="Mock 1 reply")
    mock2 = MockModelProvider(default_response="Mock 2 fallback reply")

    registry.register_provider("primary", mock1, default_model="p1-model")
    registry.register_provider("secondary", mock2, default_model="p2-model")
    registry.set_active_provider("primary")

    assert registry.active_provider_name == "primary"
    assert registry.get_active_model() == "p1-model"

    req = ChatCompletionRequest(
        model="auto",
        messages=[ChatMessage(role="user", content="Ping")]
    )
    # Success on active provider
    res = await registry.chat_completion(req)
    assert res.content == "Mock 1 reply"

    # Make primary raise ProviderUnavailableError to test fallback
    with patch.object(mock1, "chat_completion", side_effect=ProviderUnavailableError("Offline")):
        # Ensure fallback provider is registered
        registry._fallback_provider_name = "secondary"
        fallback_res = await registry.chat_completion(req)
        assert fallback_res.content == "Mock 2 fallback reply"


@pytest.mark.asyncio
async def test_ollama_capabilities_and_streaming():
    provider = OllamaProvider(base_url="http://127.0.0.1:11434")

    # Mock get_capabilities
    mock_client = AsyncMock()
    show_resp = MagicMock(status_code=200)
    show_resp.json.return_value = {
        "parameters": "num_ctx 8192\ntemperature 0.7",
        "details": {"family": "llama", "parameter_size": "7B"}
    }
    mock_client.post.return_value = show_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch.object(provider, "_get_client", return_value=mock_client):
        caps = await provider.get_capabilities("llama3")
        assert caps.context_window == 8192
        assert caps.supports_tools is True

    # Mock chat_completion_stream
    class MockStreamResp:
        def __init__(self):
            self.status_code = 200

        async def aiter_lines(self):
            yield json.dumps({"message": {"content": "Streamed "}, "done": False})
            yield json.dumps({"message": {"content": "Ollama text"}, "done": True})

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_client.stream = MagicMock(return_value=MockStreamResp())
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = ChatCompletionRequest(model="llama3", messages=[ChatMessage(role="user", content="Hi")])
        chunks = []
        async for chunk in provider.chat_completion_stream(req):
            if chunk.delta_content:
                chunks.append(chunk.delta_content)
        assert "".join(chunks) == "Streamed Ollama text"


@pytest.mark.asyncio
async def test_llama_cpp_health_models_and_streaming():
    provider = LlamaCppProvider(base_url="http://127.0.0.1:8080")

    mock_client = AsyncMock()
    # Health check
    health_resp = MagicMock(status_code=200)
    health_resp.json.return_value = {"status": "ok"}
    mock_client.get.return_value = health_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch.object(provider, "_get_client", return_value=mock_client):
        health = await provider.health_check()
        assert health.is_available is True

    # List models
    models_resp = MagicMock(status_code=200)
    models_resp.json.return_value = {"data": [{"id": "llama-cpp-v1"}]}
    mock_client.get.return_value = models_resp
    with patch.object(provider, "_get_client", return_value=mock_client):
        models = await provider.list_models()
        assert len(models) == 1
        assert models[0].name == "llama-cpp-v1"

    # Streaming SSE
    class MockSSEResp:
        def __init__(self):
            self.status_code = 200

        async def aiter_lines(self):
            yield 'data: {"choices": [{"delta": {"content": "Llama"}}]}'
            yield 'data: {"choices": [{"delta": {"content": " stream"}}]}'
            yield 'data: [DONE]'

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    mock_client.stream = MagicMock(return_value=MockSSEResp())
    with patch.object(provider, "_get_client", return_value=mock_client):
        req = ChatCompletionRequest(model="llama-cpp-v1", messages=[ChatMessage(role="user", content="Hi")])
        chunks = []
        async for chunk in provider.chat_completion_stream(req):
            if chunk.delta_content:
                chunks.append(chunk.delta_content)
        assert "".join(chunks) == "Llama stream"

