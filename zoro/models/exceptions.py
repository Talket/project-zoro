"""Normalized exceptions for AI model providers."""

from __future__ import annotations


class ModelProviderError(Exception):
    """Base exception for all AI model provider errors."""

    def __init__(self, message: str, provider_name: str = "unknown", model_name: str = "unknown") -> None:
        super().__init__(message)
        self.message = message
        self.provider_name = provider_name
        self.model_name = model_name


class ProviderUnavailableError(ModelProviderError):
    """Raised when an AI provider runtime (e.g. Ollama, llama-server) is not running or unreachable."""
    pass


class ProviderTimeoutError(ModelProviderError):
    """Raised when a request to an AI provider exceeds its timeout ceiling."""
    pass


class ModelNotFoundError(ModelProviderError):
    """Raised when the specified model is not installed or loaded in the runtime."""
    pass


class CapabilityNotSupportedError(ModelProviderError):
    """Raised when an operation requires a capability (e.g. tool calling, JSON schema) not supported by the model."""
    pass


class StructuredOutputError(ModelProviderError):
    """Raised when the model's response fails JSON schema or Pydantic validation."""
    pass


class ContextWindowExceededError(ModelProviderError):
    """Raised when the conversation context exceeds the model's maximum context length."""
    pass


class ContextLengthExceededError(ContextWindowExceededError):
    """Alias for ContextWindowExceededError."""
    pass


class AuthenticationError(ModelProviderError):
    """Raised when authentication credentials or token are invalid."""
    pass


class RateLimitError(ModelProviderError):
    """Raised when provider rate limits are hit."""
    pass
