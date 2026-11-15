"""Deterministic Mock Model Provider for testing, verification, and offline development."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional
from zoro.models.base import (
    BaseModelProvider,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelCapabilities,
    ModelInfo,
    ProviderHealth,
)


class MockModelProvider(BaseModelProvider):
    """Provides deterministic responses for test suites and offline verification."""

    def __init__(
        self,
        default_response: str = "Mock response from ZORO Model Subsystem.",
        capabilities: Optional[ModelCapabilities] = None,
    ) -> None:
        self.default_response = default_response
        self.is_healthy = True
        self.latency_ms = 1.2
        self.custom_capabilities = capabilities
        self.enqueued_responses: List[ChatCompletionResponse] = []
        self.recorded_requests: List[ChatCompletionRequest] = []

    def enqueue_response(self, response: ChatCompletionResponse) -> None:
        """Enqueue a custom response for the next chat_completion call."""
        self.enqueued_responses.append(response)

    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        self.recorded_requests.append(request)
        if self.enqueued_responses:
            return self.enqueued_responses.pop(0)

        # If tools provided and last message asks for tool, or response format requires JSON
        content = self.default_response
        tool_calls = None

        if request.response_format and request.response_format.get("type") == "json_object":
            content = '{"status": "success", "message": "mock structured json"}'

        return ChatCompletionResponse(
            id="mock-cmpl-12345",
            model=request.model,
            content=content,
            tool_calls=tool_calls,
            usage={"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25},
            finish_reason="stop",
        )

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionChunk]:
        self.recorded_requests.append(request)
        response = await self.chat_completion(request)
        text = response.content or ""
        words = text.split(" ")

        for i, word in enumerate(words):
            chunk_text = word if i == len(words) - 1 else word + " "
            yield ChatCompletionChunk(
                id=f"chunk-{i}",
                model=request.model,
                delta_content=chunk_text,
            )
            await asyncio.sleep(0.01)

        yield ChatCompletionChunk(
            id=f"chunk-{len(words)}",
            model=request.model,
            finish_reason="stop",
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            is_available=self.is_healthy,
            provider_name="MockModelProvider",
            active_model="mock-v1",
            latency_ms=self.latency_ms,
        )

    async def get_capabilities(self, model_name: str) -> ModelCapabilities:
        if self.custom_capabilities:
            return self.custom_capabilities
        return ModelCapabilities(
            model_name=model_name,
            context_window=4096,
            supports_tools=True,
            supports_json_schema=True,
            supports_vision=False,
            supports_streaming=True,
            vram_estimate_mb=0,
        )

    async def list_models(self) -> List[ModelInfo]:
        return [
            ModelInfo(
                name="mock-v1",
                size_bytes=1024 * 1024 * 50,
                family="mock",
                quantization="Q4_0",
                parameter_size="1B",
            ),
            ModelInfo(
                name="mock-planner-v2",
                size_bytes=1024 * 1024 * 100,
                family="mock",
                quantization="Q4_K_M",
                parameter_size="3B",
            ),
        ]
