"""Tests for the Central AI Orchestrator (Intent understanding, planning, tool dispatch, approval)."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from zoro.core.event_bus import AsyncEventBus
from zoro.models.base import ChatCompletionResponse
from zoro.models.mock import MockModelProvider
from zoro.models.registry import ProviderRegistry
from zoro.orchestrator.orchestrator import OrchestratorState, ZoroOrchestrator
from zoro.planner.models import PlanStatus
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.tools.builtin.file_tools import (
    FileDeleteTool,
    FileDiscoveryTool,
    FileMoveTool,
    ReportGeneratorTool,
)
from zoro.tools.registry import ToolRegistry


@pytest.fixture
async def orchestrator_env(tmp_path):
    db_path = tmp_path / "orch_test.db"
    db = DatabaseManager(db_path=db_path)
    await db.initialize()

    sec_dir = tmp_path / "security"
    sec_dir.mkdir(parents=True)
    gate = PermissionGate()
    audit = AuditLogger(db=db, checkpoint_path=sec_dir / "audit.checkpoint", key=b"0" * 32)
    emergency_mgr = EmergencyManager(
        halt_lock_path=sec_dir / "halt.lock",
        pid_path=sec_dir / "zoro.pid",
    )

    tool_reg = ToolRegistry(db=db, audit=audit, permission_gate=gate)
    tool_reg.register(FileDiscoveryTool(permission_gate=gate))
    tool_reg.register(ReportGeneratorTool(permission_gate=gate))
    tool_reg.register(FileMoveTool(permission_gate=gate))
    tool_reg.register(FileDeleteTool(permission_gate=gate))

    provider_reg = ProviderRegistry()
    mock_provider = MockModelProvider(default_response="JARVIS style response: At your service, sir.")
    provider_reg.register_provider("mock", mock_provider, default_model="mock-v1")

    event_bus = AsyncEventBus()

    orch = ZoroOrchestrator(
        provider_registry=provider_reg,
        tool_registry=tool_reg,
        db=db,
        audit=audit,
        event_bus=event_bus,
        emergency_mgr=emergency_mgr,
    )

    yield {
        "orchestrator": orch,
        "db": db,
        "mock_provider": mock_provider,
        "tmp_path": tmp_path,
        "sec_dir": sec_dir,
        "emergency_mgr": emergency_mgr,
    }
    await db.close()


@pytest.mark.asyncio
async def test_direct_conversation_flow(orchestrator_env):
    orch: ZoroOrchestrator = orchestrator_env["orchestrator"]
    db: DatabaseManager = orchestrator_env["db"]

    response = await orch.process_user_request("Hello ZORO, what is your status?")
    assert response.state in (OrchestratorState.COMPLETED, OrchestratorState.IDLE)
    assert "At your service" in response.message
    assert response.plan_id is None

    # Check database persistence
    conv_rows = await db.execute_read("SELECT id FROM conversations WHERE id = ?", (response.conversation_id,))
    assert len(conv_rows) == 1

    msg_rows = await db.execute_read("SELECT role, content FROM messages WHERE conversation_id = ?", (response.conversation_id,))
    assert len(msg_rows) == 2
    assert msg_rows[0][0] == "user"
    assert msg_rows[1][0] == "assistant"


@pytest.mark.asyncio
async def test_multi_step_planning_flow(orchestrator_env):
    orch: ZoroOrchestrator = orchestrator_env["orchestrator"]
    tmp_path: Path = orchestrator_env["tmp_path"]
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "file1.txt").write_text("content 1")

    # Prompt containing task intent triggers planning
    directive = f"Scan directory '{ws}' and generate summary report"
    response = await orch.process_user_request(directive)

    assert response.state in (OrchestratorState.COMPLETED, OrchestratorState.IDLE)
    assert response.plan_id is not None
    assert response.plan is not None
    assert response.plan["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_approval_pause_and_resolution(orchestrator_env):
    orch: ZoroOrchestrator = orchestrator_env["orchestrator"]
    tmp_path: Path = orchestrator_env["tmp_path"]
    src = tmp_path / "source.txt"
    src.write_text("data")
    dst = tmp_path / "dest.txt"

    directive = f"Move file '{src}' to '{dst}'"
    response = await orch.process_user_request(directive)

    assert response.state == OrchestratorState.WAITING_FOR_APPROVAL
    assert response.approval_required is not None
    token = response.approval_required["token"]
    assert token is not None
    assert src.exists()
    assert not dst.exists()

    # Resolve approval (Approve)
    resume_response = await orch.resolve_approval(token_str=token, approved=True)
    assert resume_response.state in (OrchestratorState.COMPLETED, OrchestratorState.IDLE)
    assert not src.exists()
    assert dst.exists()


@pytest.mark.asyncio
async def test_emergency_halt_blocks_request(orchestrator_env):
    orch: ZoroOrchestrator = orchestrator_env["orchestrator"]
    emergency_mgr: EmergencyManager = orchestrator_env["emergency_mgr"]

    # Trigger emergency halt
    emergency_mgr.halt_lock_path.write_text(
        json.dumps({"reason": "Simulated Security Threat", "operator": "Owner"}),
        encoding="utf-8",
    )
    is_halted, _ = emergency_mgr.is_halted()
    assert is_halted is True

    # User request must be blocked immediately
    response = await orch.process_user_request("ZORO, please execute command")
    assert response.state == OrchestratorState.FAILED
    assert "EMERGENCY HALT" in response.message
    assert response.error == "Emergency halt active"


@pytest.mark.asyncio
async def test_orchestrator_cancellation(orchestrator_env):
    orch: ZoroOrchestrator = orchestrator_env["orchestrator"]
    orch.cancel()
    assert orch._is_cancelled is True


@pytest.mark.asyncio
async def test_approval_rejection_and_idle_approval(orchestrator_env):
    orch: ZoroOrchestrator = orchestrator_env["orchestrator"]
    tmp_path: Path = orchestrator_env["tmp_path"]

    # 1. Calling resolve_approval when idle returns error
    idle_res = await orch.resolve_approval(token_str="fake-token", approved=True)
    assert "No active plan" in idle_res.message
    assert idle_res.error is not None

    # 2. Trigger task that requires approval, then reject it
    src = tmp_path / "reject_source.txt"
    src.write_text("keep me")
    dst = tmp_path / "reject_dest.txt"

    response = await orch.process_user_request(f"Move file '{src}' to '{dst}'")
    assert response.state == OrchestratorState.WAITING_FOR_APPROVAL
    token = response.approval_required["token"]

    # Reject
    reject_res = await orch.resolve_approval(token_str=token, approved=False)
    assert reject_res.state == OrchestratorState.CANCELLED
    assert "rejected" in reject_res.message.lower()
    assert src.exists()
    assert not dst.exists()

