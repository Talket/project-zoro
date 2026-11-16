"""Tests for Execution Sandbox & Resource Governance in PROJECT ZORO."""

from __future__ import annotations

import uuid
from pathlib import Path
import pytest

from zoro.computer.filesystem.models import FileRiskTier
from zoro.computer.sandbox.execution_policy import ExecutionPolicyEngine
from zoro.computer.sandbox.models import ExecutionProfile, ResourceLimits
from zoro.computer.sandbox.resource_limits import ResourceGovernor
from zoro.computer.sandbox.sandbox_manager import ExecutionSandboxManager
from zoro.computer.shell.models import CommandRiskTier
from zoro.config.settings import ZoroSettings
from zoro.storage.db import DatabaseManager


class TestExecutionPolicyEngine:
    def test_profile_a_read_only(self):
        engine = ExecutionPolicyEngine(profile=ExecutionProfile.PROFILE_A_READ_ONLY)
        # UI actions
        ok, req, _ = engine.evaluate_ui_action("inspect")
        assert ok is True
        ok, req, _ = engine.evaluate_ui_action("click")
        assert ok is False

        # Filesystem
        ok, req, _ = engine.evaluate_filesystem_action("read", FileRiskTier.READ_ONLY)
        assert ok is True
        ok, req, _ = engine.evaluate_filesystem_action("write", FileRiskTier.LOW_RISK)
        assert ok is False

        # Shell
        ok, req, _ = engine.evaluate_shell_execution(CommandRiskTier.TIER_1_SAFE)
        assert ok is True
        ok, req, _ = engine.evaluate_shell_execution(CommandRiskTier.TIER_2_MODERATE)
        assert ok is False

    def test_profile_b_standard(self):
        engine = ExecutionPolicyEngine(profile=ExecutionProfile.PROFILE_B_STANDARD)
        ok, req, _ = engine.evaluate_ui_action("click")
        assert ok is True
        assert req is False

        ok, req, _ = engine.evaluate_filesystem_action("write", FileRiskTier.LOW_RISK)
        assert ok is True
        assert req is False

        # Sensitive requires approval
        ok, req, _ = engine.evaluate_filesystem_action("write", FileRiskTier.SENSITIVE)
        assert ok is True
        assert req is True

        # Destructive blocked
        ok, req, _ = engine.evaluate_filesystem_action("delete", FileRiskTier.DESTRUCTIVE)
        assert ok is False

    def test_profile_c_restricted_modification(self):
        engine = ExecutionPolicyEngine(profile=ExecutionProfile.PROFILE_C_RESTRICTED_MODIFICATION)
        # Moderate shell allowed
        ok, req, _ = engine.evaluate_shell_execution(CommandRiskTier.TIER_2_MODERATE)
        assert ok is True
        assert req is False

        # Elevated shell requires approval
        ok, req, _ = engine.evaluate_shell_execution(CommandRiskTier.TIER_3_ELEVATED)
        assert ok is True
        assert req is True

    def test_profile_d_high_risk(self):
        engine = ExecutionPolicyEngine(profile=ExecutionProfile.PROFILE_D_HIGH_RISK)
        ok, req, _ = engine.evaluate_filesystem_action("delete", FileRiskTier.DESTRUCTIVE)
        assert ok is True
        assert req is True


class TestResourceGovernor:
    def test_screenshot_rate_limiting(self):
        limits = ResourceLimits(max_screenshots_per_minute=3)
        gov = ResourceGovernor(limits=limits)

        # 3 allowed
        assert gov.check_screenshot_rate() is True
        gov.record_screenshot()
        assert gov.check_screenshot_rate() is True
        gov.record_screenshot()
        assert gov.check_screenshot_rate() is True
        gov.record_screenshot()

        # 4th blocked
        assert gov.check_screenshot_rate() is False

    def test_task_concurrency_slots(self):
        limits = ResourceLimits(max_concurrent_tasks=2)
        gov = ResourceGovernor(limits=limits)

        assert gov.acquire_task_slot() is True
        assert gov.acquire_task_slot() is True
        assert gov.acquire_task_slot() is False

        gov.release_task_slot()
        assert gov.acquire_task_slot() is True

    def test_system_health(self):
        gov = ResourceGovernor()
        ok, msg = gov.check_system_health()
        assert isinstance(ok, bool)
        assert isinstance(msg, str)


class TestExecutionSandboxManager:
    @pytest.mark.asyncio
    async def test_session_lifecycle_and_db_auditing(self, tmp_path: Path):
        db_path = tmp_path / "sandbox_test.db"
        settings = ZoroSettings(
            app_data_dir=tmp_path,
            db_path=db_path,
        )
        db = DatabaseManager(settings=settings)
        await db.initialize()

        mgr = ExecutionSandboxManager(db=db)
        session = await mgr.create_session(profile=ExecutionProfile.PROFILE_B_STANDARD)
        assert session.id is not None
        assert session.profile == ExecutionProfile.PROFILE_B_STANDARD
        assert session.status == "ACTIVE"

        # Record action
        act_id = await mgr.record_action(
            action_type="ui.click",
            target="SubmitButton",
            parameters={"x": 100, "y": 200},
            risk_tier="LOW_RISK",
            status="COMPLETED",
            verified=True,
        )
        assert act_id is not None

        # Record shell
        sh_id = await mgr.record_shell_execution(
            command="python --version",
            args=["python", "--version"],
            returncode=0,
            stdout="Python 3.12.10",
            stderr="",
            duration=0.05,
            risk_tier="TIER_1_SAFE",
        )
        assert sh_id is not None

        # End session
        assert await mgr.end_session(session.id) is True
        assert mgr.current_session.status == "COMPLETED"

        await db.close()
