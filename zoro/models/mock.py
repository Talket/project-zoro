"""Deterministic Mock Model Provider for testing and offline development."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from zoro.models.base import (
    BaseModelProvider,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelCapabilities,
    ProviderHealth,
)


class MockModelProvider(BaseModelProvider):
    """Provides deterministic responses for test suites and offline verification."""

    def __init__(self, default_response: str = "Mock response from ZORO Model Subsystem.") -> None:
        self.default_response = default_response
        self.is_healthy = True

    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id="mock-cmpl-12345",
            model=request.model,
            content=self.default_response,
            usage={"prompt_tokens": 15, "completion_tokens": 10, "total_tokens": 25},
            finish_reason="stop",
        )

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            is_available=self.is_healthy,
            provider_name="MockModelProvider",
            active_model="mock-v1",
            latency_ms=1.2,
        )

    async def get_capabilities(self, model_name: str) -> ModelCapabilities:
        return ModelCapabilities(
            model_name=model_name,
            context_window=4096,
            supports_tools=True,
            supports_json_schema=True,
            supports_vision=False,
            vram_estimate_mb=0,
        )
