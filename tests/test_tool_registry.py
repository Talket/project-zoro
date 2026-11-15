"""Tests for the Secure Tool Registry, Permission Gates, and Built-in File Tools."""

import json
import time
import pytest
from pathlib import Path

from zoro.security.audit import AuditLogger
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.tools.base import ApprovalStatus, ToolContext, ToolPermissionTier
from zoro.tools.builtin.file_tools import (
    FileDeleteTool,
    FileDiscoveryTool,
    FileMoveTool,
    FileReadMetadataTool,
    ReportGeneratorTool,
)
from zoro.tools.registry import ToolRegistry


@pytest.fixture
async def test_env(tmp_path):
    db_path = tmp_path / "test_tools.db"
    db = DatabaseManager(db_path=db_path)
    await db.initialize()

    sec_dir = tmp_path / "security"
    sec_dir.mkdir(parents=True)
    gate = PermissionGate()
    audit = AuditLogger(db=db, checkpoint_path=sec_dir / "audit.checkpoint", key=b"0" * 32)

    registry = ToolRegistry(db=db, audit=audit, permission_gate=gate)
    registry.register(FileDiscoveryTool(permission_gate=gate))
    registry.register(FileReadMetadataTool(permission_gate=gate))
    registry.register(ReportGeneratorTool(permission_gate=gate))
    registry.register(FileMoveTool(permission_gate=gate))
    registry.register(FileDeleteTool(permission_gate=gate))

    yield {
        "db": db,
        "gate": gate,
        "audit": audit,
        "registry": registry,
        "tmp_path": tmp_path,
        "sec_dir": sec_dir,
    }
    await db.close()


@pytest.mark.asyncio
async def test_tool_registration_and_schemas(test_env):
    reg: ToolRegistry = test_env["registry"]
    tools = reg.list_tools()
    assert len(tools) == 5
    names = [t["name"] for t in tools]
    assert "file_discovery" in names
    assert "file_delete" in names

    # Duplicate registration should raise ValueError
    with pytest.raises(ValueError, match="already registered"):
        reg.register(FileDiscoveryTool())

    # Provider schemas
    schemas = reg.get_schemas_for_provider()
    assert len(schemas) == 5
    assert all("type" in s and s["type"] == "function" for s in schemas)


@pytest.mark.asyncio
async def test_read_only_and_low_risk_execution(test_env):
    reg: ToolRegistry = test_env["registry"]
    tmp_path: Path = test_env["tmp_path"]

    # Create dummy files
    sub_dir = tmp_path / "workspace"
    sub_dir.mkdir()
    f1 = sub_dir / "test1.txt"
    f1.write_text("Hello world 1", encoding="utf-8")
    f2 = sub_dir / "test2.log"
    f2.write_text("Log content", encoding="utf-8")

    # 1. File Discovery
    res = await reg.execute_tool(
        "file_discovery",
        {"directory": str(sub_dir), "pattern": "*.txt"},
    )
    assert res.success is True
    assert res.data["count"] == 1
    assert res.data["files"][0]["name"] == "test1.txt"

    # 2. File Metadata
    res_meta = await reg.execute_tool(
        "file_read_metadata",
        {"file_path": str(f1)},
    )
    assert res_meta.success is True
    assert res_meta.data["size_bytes"] == len("Hello world 1")
    assert res_meta.data["extension"] == ".txt"

    # 3. Report Generator (LOW_RISK)
    report_file = sub_dir / "report.md"
    res_rep = await reg.execute_tool(
        "report_generator",
        {
            "output_path": str(report_file),
            "title": "System Audit",
            "content": "All systems operational.",
        },
    )
    assert res_rep.success is True
    assert report_file.exists()
    assert "# System Audit" in report_file.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_sensitive_and_destructive_approval_gate(test_env):
    reg: ToolRegistry = test_env["registry"]
    tmp_path: Path = test_env["tmp_path"]
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    src = work_dir / "important.doc"
    src.write_text("Confidential", encoding="utf-8")
    dst = work_dir / "archived.doc"

    # SENSITIVE: Attempt file_move without approval token
    res_denied = await reg.execute_tool(
        "file_move",
        {"source_path": str(src), "destination_path": str(dst)},
    )
    assert res_denied.success is False
    assert "requires explicit approval" in res_denied.error
    assert src.exists()

    # Create approval token
    token = reg.create_approval_token("file_move", "Move important document", step_id="step-1")
    assert token.status == ApprovalStatus.PENDING

    # Attempt execution while still PENDING
    ctx = ToolContext(approval_token=token.token, step_id="step-1")
    res_pending = await reg.execute_tool(
        "file_move",
        {"source_path": str(src), "destination_path": str(dst)},
        context=ctx,
    )
    assert res_pending.success is False
    assert "not approved" in res_pending.error

    # Approve token
    assert reg.approve_token(token.token) is True
    assert token.status == ApprovalStatus.APPROVED

    # Execution should now succeed
    res_approved = await reg.execute_tool(
        "file_move",
        {"source_path": str(src), "destination_path": str(dst)},
        context=ctx,
    )
    assert res_approved.success is True
    assert not src.exists()
    assert dst.exists()
    assert token.status == ApprovalStatus.CONSUMED

    # Replay Protection: Reusing the same token MUST fail
    res_replay = await reg.execute_tool(
        "file_move",
        {"source_path": str(dst), "destination_path": str(src)},
        context=ctx,
    )
    assert res_replay.success is False
    assert "Replay detected" in res_replay.error


@pytest.mark.asyncio
async def test_destructive_file_delete_and_scope_mismatch(test_env):
    reg: ToolRegistry = test_env["registry"]
    tmp_path: Path = test_env["tmp_path"]
    target = tmp_path / "obsolete.tmp"
    target.write_text("Delete me", encoding="utf-8")

    # Create token for file_move instead of file_delete
    token_move = reg.create_approval_token("file_move", "Move something")
    reg.approve_token(token_move.token)

    # Attempt using file_move token for file_delete
    ctx_mismatch = ToolContext(approval_token=token_move.token)
    res_mismatch = await reg.execute_tool(
        "file_delete",
        {"file_path": str(target)},
        context=ctx_mismatch,
    )
    assert res_mismatch.success is False
    assert "Approval token mismatch" in res_mismatch.error
    assert target.exists()

    # Now create valid token for file_delete
    token_del = reg.create_approval_token("file_delete", "Permanently delete temp file")
    reg.approve_token(token_del.token)

    ctx_del = ToolContext(approval_token=token_del.token)
    res_del = await reg.execute_tool(
        "file_delete",
        {"file_path": str(target)},
        context=ctx_del,
    )
    assert res_del.success is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_protected_security_path_blocking(test_env):
    reg: ToolRegistry = test_env["registry"]
    sec_dir: Path = test_env["sec_dir"]

    # Try to delete protected security checkpoint
    protected_file = sec_dir / "audit.checkpoint"
    protected_file.write_text("checkpoint data")

    token = reg.create_approval_token("file_delete", "Try deleting security checkpoint")
    reg.approve_token(token.token)

    res = await reg.execute_tool(
        "file_delete",
        {"file_path": str(protected_file)},
        context=ToolContext(approval_token=token.token),
    )
    assert res.success is False
    assert "protected" in res.error.lower()
    assert protected_file.exists()


@pytest.mark.asyncio
async def test_argument_schema_validation_failure(test_env):
    reg: ToolRegistry = test_env["registry"]
    # Missing required 'directory' argument
    res = await reg.execute_tool("file_discovery", {"pattern": "*.py"})
    assert res.success is False
    assert "Invalid arguments" in res.error


@pytest.mark.asyncio
async def test_db_and_audit_logging_of_executions(test_env):
    reg: ToolRegistry = test_env["registry"]
    db: DatabaseManager = test_env["db"]
    tmp_path: Path = test_env["tmp_path"]

    res = await reg.execute_tool(
        "file_discovery",
        {"directory": str(tmp_path), "pattern": "*"},
    )
    assert res.success is True

    # Check SQLite tool_executions
    rows = await db.execute_read("SELECT tool_name, status FROM tool_executions")
    assert len(rows) >= 1
    assert rows[-1][0] == "file_discovery"
    assert rows[-1][1] == "SUCCESS"

    # Check chained audit records
    audit_rows = await db.execute_read("SELECT action, resource FROM audit_records WHERE actor = 'ToolRegistry'")
    assert len(audit_rows) >= 1
    assert "TOOL_EXECUTE_SUCCESS" in audit_rows[-1][0]


@pytest.mark.asyncio
async def test_tool_registry_rejections_timeouts_and_lifecycle(test_env):
    reg: ToolRegistry = test_env["registry"]
    tmp_path: Path = test_env["tmp_path"]

    # 1. Reject token
    token = reg.create_approval_token("file_delete", "Delete test")
    assert reg.reject_token(token.token) is True
    assert token.status == ApprovalStatus.REJECTED
    assert reg.reject_token("nonexistent-token") is False
    assert reg.approve_token("nonexistent-token") is False

    # Attempt execution with rejected token
    res = await reg.execute_tool(
        "file_delete",
        {"file_path": str(tmp_path / "dummy.txt")},
        context=ToolContext(approval_token=token.token),
    )
    assert res.success is False
    assert "rejected" in res.error

    # 2. Expired token
    token_exp = reg.create_approval_token("file_delete", "Expire test")
    token_exp.expires_at_epoch = time.time() - 100
    assert reg.approve_token(token_exp.token) is False
    assert token_exp.status == ApprovalStatus.EXPIRED

    # 3. Unknown token string
    res_unknown = await reg.execute_tool(
        "file_delete",
        {"file_path": str(tmp_path / "dummy.txt")},
        context=ToolContext(approval_token="fake-token-1234"),
    )
    assert res_unknown.success is False
    assert "Invalid or unknown" in res_unknown.error

    # 4. Unregistered tool execution
    res_unreg = await reg.execute_tool("phantom_tool", {})
    assert res_unreg.success is False
    assert "not registered" in res_unreg.error

    # 5. Tool unregister
    reg.unregister("file_delete")
    with pytest.raises(ValueError, match="not registered"):
        reg.get_tool("file_delete")

