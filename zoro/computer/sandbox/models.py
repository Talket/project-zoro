"""Models for Execution Sandbox & Resource Governance in PROJECT ZORO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ExecutionProfile(str, Enum):
    """Execution sandbox isolation profiles."""
    PROFILE_A_READ_ONLY = "PROFILE_A_READ_ONLY"
    PROFILE_B_STANDARD = "PROFILE_B_STANDARD"
    PROFILE_C_RESTRICTED_MODIFICATION = "PROFILE_C_RESTRICTED_MODIFICATION"
    PROFILE_D_HIGH_RISK = "PROFILE_D_HIGH_RISK"


@dataclass
class ResourceLimits:
    """Resource constraints for computer control operations."""
    max_concurrent_tasks: int = 3
    max_screenshots_per_minute: int = 60
    max_active_processes: int = 10
    max_cpu_percent: float = 85.0
    max_memory_mb: float = 4096.0
    task_timeout_seconds: float = 300.0


@dataclass
class ComputerSession:
    """Represents an active or historical computer control session."""
    id: str
    profile: ExecutionProfile = ExecutionProfile.PROFILE_B_STANDARD
    status: str = "ACTIVE"
    user_approved: bool = True
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None
