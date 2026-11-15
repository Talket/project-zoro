"""Base interfaces, permission classifications, and schemas for the Secure Tool Registry."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
import secrets
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel, Field


class ToolPermissionTier(str, Enum):
    """
    Hierarchical capability permission classifications.
    Enforced by application-level validation logic, never by model outputs.
    """
    READ_ONLY = "READ_ONLY"              # File metadata inspection, read operations (Auto-allowed)
    LOW_RISK = "LOW_RISK"                # Creating scratch reports, logging (Allowed with audit log)
    SENSITIVE = "SENSITIVE"              # Moving user files, modifying configs (Requires explicit owner approval)
    DESTRUCTIVE = "DESTRUCTIVE"          # Permanent deletion, killing processes (Requires explicit owner approval)
    SYSTEM_CRITICAL = "SYSTEM_CRITICAL"  # Registry, OS-level security changes (Requires elevation + approval)


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class ApprovalToken(BaseModel):
    """Single-use, cryptographically generated approval token with replay protection."""
    token: str = Field(default_factory=lambda: secrets.token_hex(16))
    tool_name: str
    permission_tier: ToolPermissionTier
    description: str
    step_id: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    expires_at_epoch: float = Field(default_factory=lambda: datetime.now(timezone.utc).timestamp() + 300.0)  # 5 min


class ToolContext(BaseModel):
    """Execution context provided to tools during execution."""
    caller: str = "orchestrator"
    session_id: Optional[str] = None
    step_id: Optional[str] = None
    approval_token: Optional[str] = None


class ToolResult(BaseModel):
    """Standardized output container for tool executions."""
    success: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_duration_ms: float = 0.0


class BaseTool(ABC):
    """Abstract base class for all tools registered in ZORO."""

    name: str
    title: str
    description: str
    permission_tier: ToolPermissionTier
    input_schema: Type[BaseModel]
    output_schema: Type[BaseModel]
    timeout_seconds: float = 30.0

    @abstractmethod
    async def execute(self, params: BaseModel, context: ToolContext) -> BaseModel:
        """
        Execute tool operation.
        Inputs are guaranteed to have been validated against input_schema.
        Outputs must conform to output_schema.
        """
        pass

    def get_json_schema(self) -> Dict[str, Any]:
        """Generate OpenAI/Ollama compatible function definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema.model_json_schema(),
            },
        }
