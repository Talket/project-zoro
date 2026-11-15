"""Model Abstraction Layer defining unified interfaces for local and remote LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # system, user, assistant, tool
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 1024
    tools: Optional[List[Dict[str, Any]]] = None
    response_format: Optional[Dict[str, Any]] = None  # JSON schema mode {"type": "json_object"}
    stream: bool = False
    timeout_seconds: float = 60.0


class ChatCompletionResponse(BaseModel):
    id: str
    model: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Dict[str, int] = Field(default_factory=dict)
    finish_reason: str = "stop"


class ChatCompletionChunk(BaseModel):
    id: str
    model: str
    delta_content: Optional[str] = None
    delta_tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None


class ModelCapabilities(BaseModel):
    model_name: str
    context_window: int = 4096
    supports_tools: bool = False
    supports_json_schema: bool = False
    supports_vision: bool = False
    supports_streaming: bool = True
    vram_estimate_mb: int = 0


class ModelInfo(BaseModel):
    name: str
    size_bytes: Optional[int] = None
    modified_at: Optional[str] = None
    family: Optional[str] = None
    quantization: Optional[str] = None
    parameter_size: Optional[str] = None


class ProviderHealth(BaseModel):
    is_available: bool
    provider_name: str
    active_model: Optional[str] = None
    latency_ms: Optional[float] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class BaseModelProvider(ABC):
    """Abstract interface decoupling ZORO from specific LLM runtimes."""

    @abstractmethod
    async def chat_completion(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        """Generate a complete chat completion."""
        pass

    @abstractmethod
    async def chat_completion_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[ChatCompletionChunk]:
        """Stream chat completion chunks asynchronously."""
        pass

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Verify provider availability, responsiveness, and loaded model state."""
        pass

    @abstractmethod
    async def get_capabilities(self, model_name: str) -> ModelCapabilities:
        """Query supported context length, tool calling, and schema constraints."""
        pass

    @abstractmethod
    async def list_models(self) -> List[ModelInfo]:
        """List models available in the runtime."""
        pass
