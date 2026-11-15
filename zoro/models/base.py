"""Model Abstraction Layer defining unified interfaces for local and remote LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: str  # system, user, assistant, tool
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 1024
    tools: Optional[List[Dict[str, Any]]] = None
    response_format: Optional[Dict[str, Any]] = None  # JSON schema mode


class ChatCompletionResponse(BaseModel):
    id: str
    model: str
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    usage: Dict[str, int] = Field(default_factory=dict)
    finish_reason: str = "stop"


class ModelCapabilities(BaseModel):
    model_name: str
    context_window: int
    supports_tools: bool
    supports_json_schema: bool
    supports_vision: bool = False
    vram_estimate_mb: int


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
        """Generate a chat completion from the underlying model runtime."""
        pass

    @abstractmethod
    async def health_check(self) -> ProviderHealth:
        """Verify provider availability, responsiveness, and loaded model state."""
        pass

    @abstractmethod
    async def get_capabilities(self, model_name: str) -> ModelCapabilities:
        """Query supported context length, tool calling, and schema constraints."""
        pass
