"""Ollama local AI runtime adapter."""

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
    ChatMessage,
    ModelCapabilities,
    ModelInfo,
    ProviderHealth,
)
from zoro.models.exceptions import (
    CapabilityNotSupportedError,
    ModelNotFoundError,
    ModelProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

logger = logging.getLogger(__name__)


class OllamaProvider(BaseModelProvider):
    """Adapter for Ollama local inference runtime (http://127.0.0.1:11434)."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
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
                resp = await client.get("/api/version", timeout=5.0)
                latency = round((time.perf_counter() - start) * 1000, 2)
                if resp.status_code == 200:
                    version_data = resp.json()
                    return ProviderHealth(
                        is_available=True,
                        provider_name="Ollama",
                        active_model=None,
                        latency_ms=latency,
                        details={"version": version_data.get("version", "unknown")},
                    )
                return ProviderHealth(
                    is_available=False,
                    provider_name="Ollama",
                    latency_ms=latency,
                    details={"http_status": resp.status_code},
                )
        except (httpx.ConnectError, httpx.NetworkError):
            return ProviderHealth(
                is_available=False,
                provider_name="Ollama",
                details={"error": "Cannot connect to Ollama runtime daemon."},
            )
        except Exception as e:
            return ProviderHealth(
                is_available=False,
                provider_name="Ollama",
                details={"error": str(e)},
            )

    async def list_models(self) -> List[ModelInfo]:
        try:
            async with self._get_client() as client:
                resp = await client.get("/api/tags", timeout=10.0)
                if resp.status_code != 200:
                    raise ProviderUnavailableError(
                        f"Ollama returned HTTP {resp.status_code}", provider_name="Ollama"
                    )
                data = resp.json()
                models = []
                for item in data.get("models", []):
                    details = item.get("details", {})
                    models.append(
                        ModelInfo(
                            name=item.get("name", ""),
                            size_bytes=item.get("size"),
                            modified_at=item.get("modified_at"),
                            family=details.get("family"),
                            quantization=details.get("quantization_level"),
                            parameter_size=details.get("parameter_size"),
                        )
                    )
                return models
        except httpx.ConnectError as exc:
            raise ProviderUnavailableError(
                "Ollama daemon is offline.", provider_name="Ollama"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "Ollama tags request timed out.", provider_name="Ollama"
            ) from exc

    async def get_capabilities(self, model_name: str) -> ModelCapabilities:
        try:
            async with self._get_client() as client:
                resp = await client.post("/api/show", json={"name": model_name}, timeout=10.0)
                if resp.status_code == 404:
                    raise ModelNotFoundError(
                        f"Model '{model_name}' not found in Ollama.",
                        provider_name="Ollama",
                        model_name=model_name,
                    )
                if resp.status_code != 200:
                    raise ModelProviderError(
                        f"Failed to inspect model '{model_name}': HTTP {resp.status_code}",
                        provider_name="Ollama",
                        model_name=model_name,
                    )

                data = resp.json()
                params = data.get("parameters", "")
                context_length = 4096
                # Parse num_ctx if present
                for line in params.splitlines():
                    if "num_ctx" in line:
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            context_length = int(parts[1])

                details = data.get("details", {})
                family = details.get("family", "").lower()
                # Most modern Qwen, Llama 3, Mistral models in Ollama support tools
                supports_tools = any(f in family for f in ["qwen", "llama", "mistral", "command-r"])

                return ModelCapabilities(
                    model_name=model_name,
                    context_window=context_length,
                    supports_tools=supports_tools,
                    supports_json_schema=True,
                    supports_vision="vision" in family or "llava" in family,
                    supports_streaming=True,
                    vram_estimate_mb=1800 if "3b" in model_name.lower() else 3500,
                )
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(
                "Ollama is unreachable.", provider_name="Ollama", model_name=model_name
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "Ollama model inspection timed out.", provider_name="Ollama", model_name=model_name
            ) from exc

    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        payload = self._build_chat_payload(request, stream=False)
        try:
            async with self._get_client() as client:
                resp = await client.post("/api/chat", json=payload, timeout=request.timeout_seconds)
                if resp.status_code == 404:
                    raise ModelNotFoundError(
                        f"Model '{request.model}' not found in Ollama.",
                        provider_name="Ollama",
                        model_name=request.model,
                    )
                if resp.status_code != 200:
                    raise ModelProviderError(
                        f"Ollama chat completion failed with HTTP {resp.status_code}: {resp.text}",
                        provider_name="Ollama",
                        model_name=request.model,
                    )

                data = resp.json()
                msg = data.get("message", {})
                content = msg.get("content")
                tool_calls = msg.get("tool_calls")

                eval_count = data.get("eval_count", 0)
                prompt_eval_count = data.get("prompt_eval_count", 0)

                return ChatCompletionResponse(
                    id=f"ollama-{int(time.time() * 1000)}",
                    model=request.model,
                    content=content,
                    tool_calls=tool_calls,
                    usage={
                        "prompt_tokens": prompt_eval_count,
                        "completion_tokens": eval_count,
                        "total_tokens": prompt_eval_count + eval_count,
                    },
                    finish_reason="stop" if data.get("done") else "unknown",
                )
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(
                "Cannot connect to Ollama runtime.", provider_name="Ollama", model_name=request.model
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                f"Ollama chat completion timed out after {request.timeout_seconds}s.",
                provider_name="Ollama",
                model_name=request.model,
            ) from exc

    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionChunk]:
        payload = self._build_chat_payload(request, stream=True)
        try:
            client = self._get_client()
            async with client.stream(
                "POST", "/api/chat", json=payload, timeout=request.timeout_seconds
            ) as response:
                if response.status_code == 404:
                    raise ModelNotFoundError(
                        f"Model '{request.model}' not found in Ollama.",
                        provider_name="Ollama",
                        model_name=request.model,
                    )
                if response.status_code != 200:
                    raise ModelProviderError(
                        f"Ollama stream failed with HTTP {response.status_code}",
                        provider_name="Ollama",
                        model_name=request.model,
                    )

                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk_json = json.loads(line)
                        msg = chunk_json.get("message", {})
                        delta = msg.get("content")
                        tool_calls = msg.get("tool_calls")
                        done = chunk_json.get("done", False)

                        yield ChatCompletionChunk(
                            id=f"ollama-chunk-{int(time.time() * 1000)}",
                            model=request.model,
                            delta_content=delta,
                            delta_tool_calls=tool_calls,
                            finish_reason="stop" if done else None,
                        )
                    except json.JSONDecodeError:
                        continue
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise ProviderUnavailableError(
                "Ollama streaming disconnected.", provider_name="Ollama", model_name=request.model
            ) from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "Ollama streaming timed out.", provider_name="Ollama", model_name=request.model
            ) from exc

    def _build_chat_payload(self, request: ChatCompletionRequest, stream: bool = False) -> Dict[str, Any]:
        messages = []
        for m in request.messages:
            msg_dict: Dict[str, Any] = {"role": m.role, "content": m.content}
            if m.tool_calls:
                msg_dict["tool_calls"] = m.tool_calls
            messages.append(msg_dict)

        payload: Dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }

        # Structured JSON mode
        if request.response_format and request.response_format.get("type") == "json_object":
            payload["format"] = "json"

        # Tools
        if request.tools:
            payload["tools"] = request.tools

        return payload
