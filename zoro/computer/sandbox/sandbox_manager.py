"""Execution Sandbox Manager for PROJECT ZORO.

Coordinates execution profiles, resource governing, Job Object process containment,
and database session auditing for all computer control actions.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from zoro.computer.sandbox.execution_policy import ExecutionPolicyEngine
from zoro.computer.sandbox.models import ComputerSession, ExecutionProfile, ResourceLimits
from zoro.computer.sandbox.resource_limits import ResourceGovernor
from zoro.security.job_object import WindowsJobObject
from zoro.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class ExecutionSandboxManager:
    """Manages active computer control sessions, policy checks, and execution auditing."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        policy: Optional[ExecutionPolicyEngine] = None,
        governor: Optional[ResourceGovernor] = None,
        job_object: Optional[WindowsJobObject] = None,
    ) -> None:
        self.db = db
        self.policy = policy or ExecutionPolicyEngine()
        self.governor = governor or ResourceGovernor()
        self.job_object = job_object
        self._current_session: Optional[ComputerSession] = None

    @property
    def current_session(self) -> Optional[ComputerSession]:
        return self._current_session

    async def create_session(
        self,
        profile: ExecutionProfile = ExecutionProfile.PROFILE_B_STANDARD,
    ) -> ComputerSession:
        """Initializes a new computer control session."""
        session_id = str(uuid.uuid4())
        session = ComputerSession(
            id=session_id,
            profile=profile,
            status="ACTIVE",
            user_approved=True,
            started_at=datetime.now(timezone.utc),
        )
        self._current_session = session
        self.policy.set_profile(profile)

        if self.db is not None:
            try:
                await self.db.execute(
                    """
                    INSERT INTO computer_sessions (id, profile, status, user_approved, started_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session.id, session.profile.value, session.status, 1, session.started_at.isoformat()),
                )
            except Exception as e:
                logger.error("Failed to record computer session to db: %s", e)

        logger.info("Initialized Computer Control Session %s under %s", session.id, profile.value)
        return session

    async def end_session(self, session_id: Optional[str] = None) -> bool:
        """Closes an active computer control session."""
        target_id = session_id or (self._current_session.id if self._current_session else None)
        if not target_id:
            return False

        ended_at = datetime.now(timezone.utc)
        if self._current_session and self._current_session.id == target_id:
            self._current_session.status = "COMPLETED"
            self._current_session.ended_at = ended_at

        if self.db is not None:
            try:
                await self.db.execute(
                    """
                    UPDATE computer_sessions
                    SET status = 'COMPLETED', ended_at = ?
                    WHERE id = ?
                    """,
                    (ended_at.isoformat(), target_id),
                )
            except Exception as e:
                logger.error("Failed to update ended session in db: %s", e)

        return True

    async def record_action(
        self,
        action_type: str,
        target: Optional[str] = None,
        parameters: Optional[dict[str, Any]] = None,
        risk_tier: str = "LOW_RISK",
        status: str = "COMPLETED",
        verified: bool = True,
        confidence: float = 1.0,
        error: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Records an executed computer action into database history."""
        action_id = str(uuid.uuid4())
        sid = session_id or (self._current_session.id if self._current_session else None)
        now = datetime.now(timezone.utc).isoformat()
        params_str = json.dumps(parameters or {})

        if self.db is not None:
            try:
                await self.db.execute(
                    """
                    INSERT INTO computer_actions (
                        id, session_id, action_type, target, parameters_json,
                        risk_tier, status, verified, confidence, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        action_id,
                        sid,
                        action_type,
                        target or "",
                        params_str,
                        risk_tier,
                        status,
                        1 if verified else 0,
                        confidence,
                        error,
                        now,
                    ),
                )
            except Exception as e:
                logger.error("Failed to record computer action to db: %s", e)

        return action_id

    async def record_shell_execution(
        self,
        command: str,
        args: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
        duration: float,
        risk_tier: str,
        session_id: Optional[str] = None,
    ) -> str:
        """Audits shell execution details into database."""
        exec_id = str(uuid.uuid4())
        sid = session_id or (self._current_session.id if self._current_session else None)
        now = datetime.now(timezone.utc).isoformat()
        args_str = json.dumps(args)

        if self.db is not None:
            try:
                await self.db.execute(
                    """
                    INSERT INTO shell_executions (
                        id, session_id, command, args_json, returncode,
                        stdout, stderr, duration_seconds, risk_tier, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        exec_id,
                        sid,
                        command,
                        args_str,
                        returncode,
                        stdout[:10000],  # truncated for db
                        stderr[:10000],
                        round(duration, 3),
                        risk_tier,
                        now,
                    ),
                )
            except Exception as e:
                logger.error("Failed to record shell execution to db: %s", e)

        return exec_id

    async def record_screenshot_metadata(
        self,
        file_path: Path,
        width: int,
        height: int,
        monitor_idx: int = 1,
        session_id: Optional[str] = None,
    ) -> str:
        """Records screenshot capture metadata into database."""
        meta_id = str(uuid.uuid4())
        sid = session_id or (self._current_session.id if self._current_session else None)
        now = datetime.now(timezone.utc).isoformat()

        if self.db is not None:
            try:
                await self.db.execute(
                    """
                    INSERT INTO screenshot_metadata (
                        id, session_id, file_path, width, height, monitor_idx, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (meta_id, sid, str(file_path), width, height, monitor_idx, now),
                )
            except Exception as e:
                logger.error("Failed to record screenshot metadata to db: %s", e)

        return meta_id
