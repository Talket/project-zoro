"""Capability-based access control and protected path authorization gate."""

from __future__ import annotations

from enum import Enum
import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class ActionTier(str, Enum):
    """Privilege tiers for system operations."""
    READ_ONLY = "READ_ONLY"
    REVERSIBLE_CHANGE = "REVERSIBLE_CHANGE"
    IRREVERSIBLE_CHANGE = "IRREVERSIBLE_CHANGE"
    SYSTEM_SETTING = "SYSTEM_SETTING"
    EXTERNAL_COMMUNICATION = "EXTERNAL_COMMUNICATION"


class PermissionDecision(str, Enum):
    """Result of a capability evaluation."""
    ALLOWED = "ALLOWED"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    DENIED = "DENIED"


class PermissionGate:
    """Evaluates capabilities and enforces protected resource boundaries."""

    PROTECTED_FILE_PATTERNS = {
        "emergency_kill.py",
        "emergency_kill.bat",
        "resume_zoro.bat",
        "supervisor.py",
        "halt.lock",
        "zoro.halt",
    }

    PROTECTED_DIR_PATTERNS = {
        "c:\\windows",
        "system32",
        "security",
    }

    def __init__(self, strict_mode: bool = True) -> None:
        self.strict_mode = strict_mode

    def is_protected_path(self, target_path: Path | str) -> bool:
        """Check if target path is a hard-locked security component."""
        path_str = str(target_path).lower().replace("/", "\\")
        
        # Check forbidden filename patterns
        for pattern in self.PROTECTED_FILE_PATTERNS:
            if path_str.endswith(pattern.lower()):
                return True
        
        # Check forbidden directories
        for dir_pattern in self.PROTECTED_DIR_PATTERNS:
            if dir_pattern in path_str:
                return True

        return False

    def evaluate(
        self,
        tier: ActionTier,
        resource: Optional[Path | str] = None,
        is_user_approved: bool = False,
    ) -> Tuple[PermissionDecision, str]:
        """
        Evaluate if an action is permitted.
        Returns (decision, justification).
        """
        # Hard lock protection on safety components
        if resource and self.is_protected_path(resource):
            if tier != ActionTier.READ_ONLY:
                msg = f"Operation BLOCKED: Target resource '{resource}' is a hard-locked security component."
                logger.warning(msg)
                return PermissionDecision.DENIED, msg

        # Read-only operations are always permitted
        if tier == ActionTier.READ_ONLY:
            return PermissionDecision.ALLOWED, "Read-only access granted."

        # Reversible changes are allowed in standard mode
        if tier == ActionTier.REVERSIBLE_CHANGE:
            return PermissionDecision.ALLOWED, "Reversible operation permitted."

        # Irreversible, system, or external actions require confirmation
        if tier in (ActionTier.IRREVERSIBLE_CHANGE, ActionTier.SYSTEM_SETTING, ActionTier.EXTERNAL_COMMUNICATION):
            if is_user_approved:
                return PermissionDecision.ALLOWED, "User explicit confirmation verified."
            return (
                PermissionDecision.REQUIRES_CONFIRMATION,
                f"Action tier {tier.value} requires explicit user approval.",
            )

        return PermissionDecision.DENIED, "Unknown action tier denied by default."
