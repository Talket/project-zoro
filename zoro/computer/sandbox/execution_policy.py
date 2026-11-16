"""Execution Policy Engine for PROJECT ZORO.

Enforces execution profiles and user approval requirements across all computer operations:
- Profile A (Read Only): strictly read/inspect actions only
- Profile B (Standard): UI interaction, Tier 1 shell, workspace filesystem writes
- Profile C (Restricted Modification): Profile B + Tier 2 shell + file edits with preview
- Profile D (High Risk): Full access with mandatory user approval dialogs
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from zoro.computer.filesystem.models import FileRiskTier
from zoro.computer.sandbox.models import ExecutionProfile
from zoro.computer.shell.models import CommandRiskTier

logger = logging.getLogger(__name__)


class ExecutionPolicyEngine:
    """Evaluates operations against the active execution profile."""

    def __init__(self, profile: ExecutionProfile = ExecutionProfile.PROFILE_B_STANDARD) -> None:
        self.profile = profile

    def set_profile(self, profile: ExecutionProfile) -> None:
        self.profile = profile
        logger.info("Switched execution profile to %s", profile.value)

    def evaluate_ui_action(self, action_type: str) -> tuple[bool, bool, str]:
        """Evaluates UI automation action. Returns (is_allowed, requires_approval, reason)."""
        if self.profile == ExecutionProfile.PROFILE_A_READ_ONLY:
            # Inspection is allowed; physical interactions are blocked
            if action_type.lower() in ("inspect", "list", "get_active", "find"):
                return True, False, "Read-only inspection permitted"
            return False, False, f"UI action '{action_type}' blocked under PROFILE_A_READ_ONLY"

        if self.profile == ExecutionProfile.PROFILE_D_HIGH_RISK:
            return True, True, "High-risk profile requires explicit approval"

        return True, False, f"Action permitted under {self.profile.value}"

    def evaluate_filesystem_action(
        self,
        op_type: str,
        risk_tier: FileRiskTier,
    ) -> tuple[bool, bool, str]:
        """Evaluates filesystem action against current profile."""
        if self.profile == ExecutionProfile.PROFILE_A_READ_ONLY:
            if risk_tier == FileRiskTier.READ_ONLY:
                return True, False, "Read-only filesystem access permitted"
            return False, False, f"Filesystem operation '{op_type}' ({risk_tier.value}) blocked under PROFILE_A_READ_ONLY"

        if self.profile == ExecutionProfile.PROFILE_B_STANDARD:
            if risk_tier in (FileRiskTier.READ_ONLY, FileRiskTier.LOW_RISK):
                return True, False, "Permitted under standard profile"
            if risk_tier == FileRiskTier.SENSITIVE:
                return True, True, "Modifying sensitive files requires user approval"
            return False, False, "Destructive filesystem operations blocked under PROFILE_B_STANDARD"

        if self.profile == ExecutionProfile.PROFILE_C_RESTRICTED_MODIFICATION:
            if risk_tier in (FileRiskTier.READ_ONLY, FileRiskTier.LOW_RISK, FileRiskTier.SENSITIVE):
                return True, False, "Permitted under restricted modification profile"
            return True, True, "Destructive filesystem operations require user approval under PROFILE_C"

        # Profile D
        return True, True, "All file modifications under PROFILE_D require user approval"

    def evaluate_shell_execution(
        self,
        risk_tier: CommandRiskTier,
    ) -> tuple[bool, bool, str]:
        """Evaluates shell execution command against current profile."""
        if risk_tier == CommandRiskTier.TIER_4_BLOCKED:
            return False, False, "Blocked by safety policy"

        if self.profile == ExecutionProfile.PROFILE_A_READ_ONLY:
            if risk_tier == CommandRiskTier.TIER_1_SAFE:
                return True, False, "Safe read-only command permitted"
            return False, False, f"Shell execution ({risk_tier.value}) blocked under PROFILE_A_READ_ONLY"

        if self.profile == ExecutionProfile.PROFILE_B_STANDARD:
            if risk_tier == CommandRiskTier.TIER_1_SAFE:
                return True, False, "Permitted under standard profile"
            if risk_tier == CommandRiskTier.TIER_2_MODERATE:
                return True, False, "Moderate command permitted in development profile"
            return False, False, f"Elevated command ({risk_tier.value}) blocked under PROFILE_B_STANDARD"

        if self.profile == ExecutionProfile.PROFILE_C_RESTRICTED_MODIFICATION:
            if risk_tier in (CommandRiskTier.TIER_1_SAFE, CommandRiskTier.TIER_2_MODERATE):
                return True, False, "Permitted under restricted modification profile"
            return True, True, "Elevated command requires approval under PROFILE_C"

        # Profile D
        return True, True, "Command execution under PROFILE_D requires user approval"
