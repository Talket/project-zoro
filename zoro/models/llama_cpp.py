"""llama.cpp / llama-server local AI runtime adapter."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator, Dict, List, Optional
import httpx

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
    ModelNotFoundError,
    ModelProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)


class LlamaCppProvider(BaseModelProvider):
    """Adapter for llama.cpp (llama-server.exe) OpenAI-compatible runtime."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        timeout_seconds: float = 60.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client
        return httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds)

    async def health_check(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            async with self._get_client() as client:
                resp = await client.get("/health", timeout=5.0)
                latency = round((time.perf_counter() - start) * 1000, 2)
                if resp.status_code == 200:
                    data = resp.json()
                    status = data.get("status", "ok")
                    return ProviderHealth(
                        is_available=status == "ok",
                        provider_name="llama.cpp",
                        latency_ms=latency,
                        details=data,
                    )
                return ProviderHealth(
                    is_available=False,
                    provider_name="llama.cpp",
                    latency_ms=latency,
                    details={"http_status": resp.status_code},
                )
        except (httpx.ConnectError, httpx.NetworkError):
            return ProviderHealth(
                is_available=False,
                provider_name="llama.cpp",
                details={"error": "Cannot connect to llama-server."},
            )
        except Exception as e:
            return ProviderHealth(
                is_available=False,
                provider_name="llama.cpp",
                details={"error": str(e)},
            )

    async def list_models(self) -> List[ModelInfo]:
        try:
            async with self._get_client() as client:
                resp = await client.get("/v1/models", timeout=10.0)
                if resp.status_code != 200:
                    raise ProviderUnavailableError(
                        f"llama-server returned HTTP {resp.status_code}", provider_name="llama.cpp"
                    )
                data = resp.json()
                models = []
                for item in data.get("data", []):
                    models.append(
                        ModelInfo(
                            name=item.get("id", "default"),
                            family="llama.cpp",
                        )
                    )
                return models
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                "llama-server is offline.", provider_name="llama.cpp"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "llama-server models request timed out.", provider_name="llama.cpp"
            ) from exc

    async def get_capabilities(self, model_name: str) -> ModelCapabilities:
        # Default Pascal CC 6.1 (GTX 1050 Ti) estimate: 4-bit 3B model fits in ~2.0 GB VRAM
        return ModelCapabilities(
            model_name=model_name,
            context_window=4096,
            supports_tools=True,
            supports_json_schema=True,
            supports_vision=False,
            supports_streaming=True,
            vram_estimate_mb=2100,
        )

    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        payload = self._build_payload(request, stream=False)
        try:
            async with self._get_client() as client:
                resp = await client.post("/v1/chat/completions", json=payload, timeout=request.timeout_seconds)
                if resp.status_code == 404:
                    raise ModelNotFoundError(
                        f"Model '{request.model}' not found in llama-server.",
                        provider_name="llama.cpp",
                        model_name=request.model,
                    )
                if resp.status_code != 200:
                    raise ModelProviderError(
                        f"llama.cpp completion failed with HTTP {resp.status_code}: {resp.text}",
                        provider_name="llama.cpp",
                        model_name=request.model,
                    )

                data = resp.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})
                content = message.get("content")
                tool_calls = message.get("tool_calls")
                usage = data.get("usage", {})

                return ChatCompletionResponse(
                    id=data.get("id", f"llama-cmpl-{int(time.time() * 1000)}"),
                    model=request.model,
                    content=content,
                    tool_calls=tool_calls,
                    usage={
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    },
                    finish_reason=choice.get("finish_reason", "stop"),
                )
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(
                "Cannot connect to llama-server.", provider_name="llama.cpp", model_name=request.model
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"llama-server request timed out after {request.timeout_seconds}s.",
                provider_name="llama.cpp",
                model_name=request.model,
            ) from exc

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionChunk]:
        payload = self._build_payload(request, stream=True)
        try:
            client = self._get_client()
            async with client.stream(
                "POST", "/v1/chat/completions", json=payload, timeout=request.timeout_seconds
            ) as response:
                if response.status_code != 200:
                    raise ModelProviderError(
                        f"llama-server streaming failed with HTTP {response.status_code}",
                        provider_name="llama.cpp",
                        model_name=request.model,
                    )

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk_json = json.loads(data_str)
                        choice = chunk_json.get("choices", [{}])[0]
                        delta = choice.get("delta", {})
                        content = delta.get("content")
                        tool_calls = delta.get("tool_calls")
                        finish = choice.get("finish_reason")

                        yield ChatCompletionChunk(
                            id=chunk_json.get("id", f"chunk-{int(time.time() * 1000)}"),
                            model=request.model,
                            delta_content=content,
                            delta_tool_calls=tool_calls,
                            finish_reason=finish,
                        )
                    except json.JSONDecodeError:
                        continue
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(
                "llama-server streaming disconnected.", provider_name="llama.cpp", model_name=request.model
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "llama-server streaming timed out.", provider_name="llama.cpp", model_name=request.model
            ) from exc

    def _build_payload(self, request: ChatCompletionRequest, stream: bool = False) -> Dict[str, Any]:
        messages = [
            {"role": m.role, "content": m.content, **({"tool_calls": m.tool_calls} if m.tool_calls else {})}
            for m in request.messages
        ]
        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": stream,
        }
        if request.response_format:
            payload["response_format"] = request.response_format
        if request.tools:
            payload["tools"] = request.tools
        return payload
