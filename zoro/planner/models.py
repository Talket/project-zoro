"""Pydantic models and schemas for Multi-Step Task Planning."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class PlanStepStatus(str, Enum):
    PENDING = "PENDING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PlanStep(BaseModel):
    """An individual discrete executable step within a task plan."""
    step_id: str = Field(default_factory=lambda: f"step-{uuid.uuid4().hex[:6]}")
    step_index: int = 0
    tool_name: str
    description: str
    input_parameters: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list, description="List of step_ids that must complete first")
    status: PlanStepStatus = PlanStepStatus.PENDING
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    requires_approval: bool = False
    approval_token: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 2
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class TaskPlan(BaseModel):
    """A validated multi-step execution plan."""
    plan_id: str = Field(default_factory=lambda: f"plan-{uuid.uuid4().hex[:8]}")
    conversation_id: Optional[str] = None
    user_request: str
    steps: List[PlanStep] = Field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None
