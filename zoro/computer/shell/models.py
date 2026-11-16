"""Models for Controlled Shell Execution in PROJECT ZORO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class CommandRiskTier(str, Enum):
    """Classification of command risk levels."""
    TIER_1_SAFE = "TIER_1_SAFE"          # Read-only information gathering
    TIER_2_MODERATE = "TIER_2_MODERATE"  # Builds, test runs, virtualenv installs
    TIER_3_ELEVATED = "TIER_3_ELEVATED"  # Modifications to environment, config, process tree
    TIER_4_BLOCKED = "TIER_4_BLOCKED"    # Destructive, formatting, security-tampering commands


@dataclass
class ShellExecutionResult:
    """Outcome of an executed command."""
    command: str
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    risk_tier: CommandRiskTier
    pid: Optional[int] = None
    timed_out: bool = False
    error: Optional[str] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ProcessInfo:
    """Snapshot of a running process."""
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float
    status: str
    is_hung: bool = False
    window_title: Optional[str] = None
