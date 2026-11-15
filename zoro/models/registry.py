"""Provider Registry managing multiple AI runtimes, active selection, and fallback cascading."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional
from zoro.models.base import (
    BaseModelProvider,
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelCapabilities,
    ModelInfo,
    ProviderHealth,
)
from zoro.models.exceptions import (
    ModelProviderError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)


class ProviderRegistry:
    """Registry coordinating multiple AI providers with automatic fallback cascading."""

    def __init__(self) -> None:
        self._providers: Dict[str, BaseModelProvider] = {}
        self._active_provider_name: str = "mock"
        self._fallback_provider_name: Optional[str] = "mock"
        self._default_models: Dict[str, str] = {
            "mock": "mock-v1",
            "ollama": "qwen2.5:3b",
            "llama.cpp": "default",
        }

    def register_provider(self, name: str, provider: BaseModelProvider, default_model: Optional[str] = None) -> None:
        self._providers[name] = provider
        if default_model:
            self._default_models[name] = default_model
        logger.info("Registered AI provider '%s'.", name)

    def unregister_provider(self, name: str) -> None:
        self._providers.pop(name, None)

    def get_provider(self, name: Optional[str] = None) -> BaseModelProvider:
        provider_name = name or self._active_provider_name
        if provider_name not in self._providers:
            raise ProviderUnavailableError(f"Provider '{provider_name}' is not registered.")
        return self._providers[provider_name]

    def set_active_provider(self, name: str, model_name: Optional[str] = None) -> None:
        if name not in self._providers:
            raise ProviderUnavailableError(f"Cannot activate unregistered provider '{name}'.")
        self._active_provider_name = name
        if model_name:
            self._default_models[name] = model_name
        logger.info("Active AI provider switched to '%s' (model: %s).", name, self._default_models.get(name))

    @property
    def active_provider_name(self) -> str:
        return self._active_provider_name

    def get_active_model(self) -> str:
        return self._default_models.get(self._active_provider_name, "default")

    async def chat_completion(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Alias for chat_completion_with_fallback."""
        return await self.chat_completion_with_fallback(request)

    async def chat_completion_with_fallback(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Attempt completion on active provider; if unavailable, cascade to fallback."""
        primary_provider = self.get_provider(self._active_provider_name)
        try:
            return await primary_provider.chat_completion(request)
        except (ProviderUnavailableError, ModelProviderError) as exc:
            if (
                self._fallback_provider_name
                and self._fallback_provider_name != self._active_provider_name
                and self._fallback_provider_name in self._providers
            ):
                logger.warning(
                    "Primary provider '%s' failed (%s). Cascading to fallback '%s'.",
                    self._active_provider_name,
                    exc,
                    self._fallback_provider_name,
                )
                fallback_provider = self._providers[self._fallback_provider_name]
                # Adjust model name for fallback if needed
                fallback_req = request.model_copy(
                    update={"model": self._default_models.get(self._fallback_provider_name, "mock-v1")}
                )
                return await fallback_provider.chat_completion(fallback_req)
            raise

    async def get_all_provider_health(self) -> Dict[str, ProviderHealth]:
        async def _check(name: str, prov: BaseModelProvider):
            try:
                return name, await asyncio.wait_for(prov.health_check(), timeout=1.0)
            except Exception as e:
                return name, ProviderHealth(
                    is_available=False,
                    provider_name=name,
                    details={"error": str(e)},
                )

        tasks = [_check(name, prov) for name, prov in self._providers.items()]
        results = await asyncio.gather(*tasks)
        return dict(results)

    async def discover_all_models(self) -> Dict[str, List[ModelInfo]]:
        catalog: Dict[str, List[ModelInfo]] = {}
        for name, provider in self._providers.items():
            try:
                models = await provider.list_models()
                catalog[name] = models
            except Exception as e:
                logger.debug("Could not list models for provider '%s': %s", name, e)
                catalog[name] = []
        return catalog
