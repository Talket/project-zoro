"""End-to-End Integration Verification for PROJECT ZORO Milestone 02: The Intelligence Core."""

import asyncio
import json
import os
import uuid
import pytest
from pathlib import Path

from zoro.config.settings import ZoroSettings
from zoro.core.engine import ZoroEngine
from zoro.ipc.pipe_client import NamedPipeClient
from zoro.security.emergency import EmergencyManager


@pytest.fixture
async def e2e_system(tmp_path):
    pipe_id = uuid.uuid4().hex[:8]
    pipe_name = rf"\\.\pipe\zoro-test-e2e-{pipe_id}"
    sec_dir = tmp_path / "security"
    sec_dir.mkdir(parents=True)
    db_path = tmp_path / "zoro_e2e.db"

    settings = ZoroSettings(
        app_data_dir=tmp_path,
        pipe_name=pipe_name,
        db_path=db_path,
        security_dir=sec_dir,
        audit_checkpoint_path=sec_dir / "audit.checkpoint",
        halt_lock_path=sec_dir / "halt.lock",
        pid_path=sec_dir / "zoro.pid",
    )

    engine = ZoroEngine(settings=settings)
    emergency_mgr = engine.emergency_mgr
    init_ok = await engine.initialize()
    assert init_ok is True

    # Connect IPC client
    client = NamedPipeClient(pipe_name=pipe_name, settings=settings)
    connected = client.connect(timeout_ms=5000)
    assert connected is True

    yield {
        "engine": engine,
        "client": client,
        "settings": settings,
        "emergency_mgr": emergency_mgr,
        "tmp_path": tmp_path,
        "sec_dir": sec_dir,
    }

    client.close()
    await engine.shutdown()


@pytest.mark.asyncio
async def test_e2e_intelligence_full_pipeline(e2e_system):
    client: NamedPipeClient = e2e_system["client"]
    engine: ZoroEngine = e2e_system["engine"]
    tmp_path: Path = e2e_system["tmp_path"]

    # 1. Verify system state via IPC
    state_res = await asyncio.to_thread(client.send_request, "system.get_state")
    assert state_res["state"] == "RUNNING"
    assert state_res["orchestrator_state"] == "IDLE"

    # 2. Query and select AI providers
    prov_res = await asyncio.to_thread(client.send_request, "ai.get_providers")
    assert "mock" in prov_res["providers"]

    select_res = await asyncio.to_thread(
        client.send_request, "ai.select_provider", {"provider": "mock", "model": "mock-v1"}
    )
    assert select_res["active_provider"] == "mock"
    assert select_res["active_model"] == "mock-v1"

    # 3. Run hardware-aware benchmark via IPC
    bench_res = await asyncio.to_thread(
        client.send_request, "ai.run_benchmark", {"provider": "mock", "model": "mock-v1"}
    )
    assert "result" in bench_res
    assert bench_res["result"]["model_name"] == "mock-v1"
    assert bench_res["result"]["tokens_per_sec"] > 0

    # 4. Direct conversational prompt via IPC
    chat_res = await asyncio.to_thread(
        client.send_request, "ai.prompt", {"message": "Hello ZORO, are all systems operational?"}
    )
    assert chat_res["state"] in ("COMPLETED", "IDLE")
    assert len(chat_res["message"]) > 0
    conv_id = chat_res["conversation_id"]

    # 5. Multi-step task plan prompt via IPC
    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir()
    (ws_dir / "data1.txt").write_text("dataset 1")
    (ws_dir / "data2.txt").write_text("dataset 2")

    task_res = await asyncio.to_thread(
        client.send_request,
        "ai.prompt",
        {"message": f"Scan directory '{ws_dir}' and generate summary report", "conversation_id": conv_id},
    )
    assert task_res["state"] in ("COMPLETED", "IDLE")
    assert task_res["plan_id"] is not None
    assert task_res["plan"]["status"] == "COMPLETED"

    # 6. SENSITIVE Tool execution requiring human approval
    src_file = ws_dir / "confidential.txt"
    src_file.write_text("Secret")
    dst_file = ws_dir / "archived.txt"

    move_res = await asyncio.to_thread(
        client.send_request,
        "ai.prompt",
        {"message": f"Move file '{src_file}' to '{dst_file}'", "conversation_id": conv_id},
    )
    assert move_res["state"] == "WAITING_FOR_APPROVAL"
    assert move_res["approval_required"] is not None
    token = move_res["approval_required"]["token"]
    assert src_file.exists()
    assert not dst_file.exists()

    # User resolves approval via IPC
    approval_res = await asyncio.to_thread(
        client.send_request, "ai.approve", {"token": token, "approved": True}
    )
    assert approval_res["state"] in ("COMPLETED", "IDLE")
    assert not src_file.exists()
    assert dst_file.exists()

    # 7. Verify SQLite Database Records across all subsystems
    db = engine.db
    conv_rows = await db.execute_read("SELECT COUNT(*) FROM conversations")
    assert conv_rows[0][0] >= 1

    msg_rows = await db.execute_read("SELECT COUNT(*) FROM messages")
    assert msg_rows[0][0] >= 4

    plan_rows = await db.execute_read("SELECT COUNT(*) FROM task_plans")
    assert plan_rows[0][0] >= 2

    step_rows = await db.execute_read("SELECT COUNT(*) FROM task_steps")
    assert step_rows[0][0] >= 2

    tool_exec_rows = await db.execute_read("SELECT COUNT(*) FROM tool_executions")
    assert tool_exec_rows[0][0] >= 2

    bench_rows = await db.execute_read("SELECT COUNT(*) FROM model_benchmarks")
    assert bench_rows[0][0] >= 1

    # 8. Verify Cryptographically Chained Audit Records
    audit_valid, corrupted_id = await engine.audit.verify_integrity()
    assert audit_valid is True
    assert corrupted_id is None


@pytest.mark.asyncio
async def test_e2e_emergency_halt_protection(e2e_system):
    client: NamedPipeClient = e2e_system["client"]
    emergency_mgr: EmergencyManager = e2e_system["emergency_mgr"]

    # Write emergency halt lock
    emergency_mgr.halt_lock_path.write_text(
        json.dumps({"reason": "Active Intrusion", "operator": "SafetyMonitor"}),
        encoding="utf-8",
    )

    # Prompt through IPC while halted
    res = await asyncio.to_thread(
        client.send_request, "ai.prompt", {"message": "Run scan now"}
    )
    assert res["state"] == "FAILED"
    assert "EMERGENCY HALT" in res["message"]
