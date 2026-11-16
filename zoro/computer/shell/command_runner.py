"""Controlled Command Runner for PROJECT ZORO.

Executes shell commands within strict security boundaries:
- Enforces command policy and risk classification
- Spawns subprocesses within Windows Job Object containment when available
- Captures stdout/stderr safely up to 1 MB
- Strictly avoids shell=True for unparsed dynamic input
"""

from __future__ import annotations

import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from zoro.computer.shell.command_policy import CommandPolicy
from zoro.computer.shell.models import CommandRiskTier, ShellExecutionResult
from zoro.security.job_object import WindowsJobObject

logger = logging.getLogger(__name__)

MAX_OUTPUT_BYTES = 1024 * 1024  # 1 MB maximum output capture


class ControlledCommandRunner:
    """Executes commands within controlled parameters and Job Object containment."""

    def __init__(
        self,
        policy: Optional[CommandPolicy] = None,
        default_timeout: float = 30.0,
        working_dir: Optional[Path] = None,
        job_object: Optional[WindowsJobObject] = None,
    ) -> None:
        self.policy = policy or CommandPolicy()
        self.default_timeout = default_timeout
        self.working_dir = working_dir or Path.cwd()
        self.job_object = job_object

    def execute(
        self,
        command: Union[str, list[str]],
        cwd: Optional[Path] = None,
        timeout: Optional[float] = None,
    ) -> ShellExecutionResult:
        """Executes a command safely, enforcing policies, limits, and containment."""
        start_time = time.time()
        start_dt = datetime.now(timezone.utc)
        effective_timeout = timeout or self.default_timeout

        # 1. Evaluate policy
        risk_tier, reason, args = self.policy.evaluate_command(command)
        cmd_str = command if isinstance(command, str) else " ".join(command)

        if risk_tier == CommandRiskTier.TIER_4_BLOCKED:
            return ShellExecutionResult(
                command=cmd_str,
                args=args,
                returncode=126,
                stdout="",
                stderr=f"Execution blocked by security policy: {reason}",
                duration_seconds=0.0,
                risk_tier=risk_tier,
                error="BlockedByPolicy",
                started_at=start_dt,
            )

        # 2. Resolve working directory
        target_cwd = (cwd or self.working_dir).resolve()
        if not target_cwd.exists():
            return ShellExecutionResult(
                command=cmd_str,
                args=args,
                returncode=1,
                stdout="",
                stderr=f"Working directory does not exist: {target_cwd}",
                duration_seconds=0.0,
                risk_tier=risk_tier,
                error="InvalidWorkingDirectory",
                started_at=start_dt,
            )

        # 3. Launch process
        try:
            # Avoid shell=True on Windows by invoking args list directly
            clean_args = [a.strip('"\'') for a in args]
            proc = subprocess.Popen(
                clean_args,
                cwd=str(target_cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                shell=False,
            )

            # Assign to Job Object if configured
            if self.job_object is not None and self.job_object.handle:
                try:
                    self.job_object.assign_process(proc.pid)
                except Exception as e_job:
                    logger.debug("Failed to assign pid %d to Job Object: %s", proc.pid, e_job)

            # Wait for completion or timeout
            try:
                stdout_raw, stderr_raw = proc.communicate(timeout=effective_timeout)
                stdout_str = stdout_raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
                stderr_str = stderr_raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
                duration = time.time() - start_time

                return ShellExecutionResult(
                    command=cmd_str,
                    args=args,
                    returncode=proc.returncode,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    duration_seconds=duration,
                    risk_tier=risk_tier,
                    pid=proc.pid,
                    timed_out=False,
                    started_at=start_dt,
                )
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout_raw, stderr_raw = proc.communicate()
                duration = time.time() - start_time
                return ShellExecutionResult(
                    command=cmd_str,
                    args=args,
                    returncode=-1,
                    stdout=stdout_raw[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace"),
                    stderr=f"Command timed out after {effective_timeout}s: {stderr_raw.decode('utf-8', errors='replace')}",
                    duration_seconds=duration,
                    risk_tier=risk_tier,
                    pid=proc.pid,
                    timed_out=True,
                    error="TimeoutExpired",
                    started_at=start_dt,
                )

        except Exception as e:
            duration = time.time() - start_time
            logger.error("Failed to execute command %s: %s", cmd_str, e)
            return ShellExecutionResult(
                command=cmd_str,
                args=args,
                returncode=-1,
                stdout="",
                stderr=str(e),
                duration_seconds=duration,
                risk_tier=risk_tier,
                error=str(e),
                started_at=start_dt,
            )
