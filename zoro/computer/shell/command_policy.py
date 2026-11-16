"""Command Policy and Risk Evaluation for PROJECT ZORO.

Evaluates commands against risk tiers, enforces executable allowlists,
and prevents command injection and critical security tampering.
"""

from __future__ import annotations

import logging
import shlex
from pathlib import Path
from typing import Optional, Union

from zoro.computer.shell.models import CommandRiskTier

logger = logging.getLogger(__name__)

# Permitted executables for controlled execution
DEFAULT_ALLOWED_EXECUTABLES = {
    "python.exe",
    "python",
    "pytest.exe",
    "pytest",
    "git.exe",
    "git",
    "cmd.exe",
    "cmd",
    "powershell.exe",
    "powershell",
    "pwsh.exe",
    "pwsh",
    "node.exe",
    "node",
    "npm.cmd",
    "npm",
    "whoami.exe",
    "whoami",
    "ipconfig.exe",
    "ipconfig",
    "systeminfo.exe",
    "systeminfo",
    "hostname.exe",
    "hostname",
    "ping.exe",
    "ping",
    "curl.exe",
    "curl",
    "echo",
    "dir",
}

# Commands and patterns strictly blocked under all circumstances
BLOCKED_PATTERNS = [
    "format ",
    "vssadmin",
    "bcdedit",
    "diskpart",
    "cipher /w",
    "del /s /q c:",
    "rmdir /s /q c:",
    "remove-item -recurse c:",
    "remove-item -recurse -force c:",
    "takeown /f c:",
    "emergency.lock",
    "audit.key",
    "zoro.pid",
    "audit.checkpoint",
    ":(){ :|:& };:",  # Fork bomb
]

# Safe read-only commands
SAFE_READ_COMMANDS = {
    "git status",
    "git log",
    "git diff",
    "git branch",
    "whoami",
    "ipconfig",
    "systeminfo",
    "hostname",
    "python --version",
    "pytest --version",
    "dir",
    "echo",
    "Get-ChildItem",
    "Get-Process",
}


class CommandPolicy:
    """Enforces execution policies and risk tier assignment on shell commands."""

    def __init__(self, allowed_executables: Optional[set[str]] = None) -> None:
        self.allowed_executables = allowed_executables or set(DEFAULT_ALLOWED_EXECUTABLES)

    def evaluate_command(
        self,
        command: Union[str, list[str]],
    ) -> tuple[CommandRiskTier, str, list[str]]:
        """Evaluates command string or argument list.

        Returns (risk_tier, reason, parsed_args_list).
        """
        if isinstance(command, str):
            raw_cmd = command.strip()
            try:
                raw_parts = shlex.split(raw_cmd, posix=False)
                parts = [p.strip('"\'') for p in raw_parts]
            except Exception as e:
                return CommandRiskTier.TIER_4_BLOCKED, f"Failed to parse command syntax: {e}", []
        else:
            parts = [str(a).strip('"\'') for a in command]
            raw_cmd = " ".join(parts)

        if not parts:
            return CommandRiskTier.TIER_4_BLOCKED, "Empty command is invalid", []

        raw_lower = raw_cmd.lower()

        # 1. Check blocked patterns (Tier 4)
        for pattern in BLOCKED_PATTERNS:
            if pattern in raw_lower:
                return (
                    CommandRiskTier.TIER_4_BLOCKED,
                    f"Command contains strictly blocked pattern: '{pattern}'",
                    parts,
                )

        # 2. Check executable allowlist
        exe_name = Path(parts[0]).name.lower()
        if exe_name not in {e.lower() for e in self.allowed_executables}:
            logger.warning("Executable '%s' is not in default allowlist", exe_name)
            # Tier 3 Elevated if executable is unknown
            return (
                CommandRiskTier.TIER_3_ELEVATED,
                f"Executable '{exe_name}' is not in approved allowlist; requires elevated approval",
                parts,
            )

        # 3. Check for safe read-only queries (Tier 1)
        for safe_cmd in SAFE_READ_COMMANDS:
            if raw_lower.startswith(safe_cmd.lower()):
                return CommandRiskTier.TIER_1_SAFE, "Safe read-only query", parts

        # 4. Check for moderate operations (Tier 2: tests, builds, local git)
        if exe_name in ("pytest", "pytest.exe") or ("git" in exe_name and ("commit" in raw_lower or "add" in raw_lower)):
            return CommandRiskTier.TIER_2_MODERATE, "Standard development/testing operation", parts

        # 5. Default to Elevated for general state-modifying commands
        return CommandRiskTier.TIER_3_ELEVATED, "State-modifying shell command", parts
