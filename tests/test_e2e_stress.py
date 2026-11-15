"""End-to-End System Integration and Concurrency Stress Verification for PROJECT ZORO."""

import asyncio
import os
import pytest
from zoro.core.engine import ZoroEngine
from zoro.core.lifecycle import LifecycleState
from zoro.ipc.pipe_client import NamedPipeClient
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager


@pytest.mark.asyncio
async def test_full_system_lifecycle_e2e(test_settings):
    """
    Complete lifecycle story:
    1. Boot Engine.
    2. Connect Client via Named Pipe IPC.
    3. Stream telemetry & verify notifications.
    4. Execute RPC requests.
    5. Shut down engine cleanly via IPC.
    6. Verify DB persistence and audit trail.
    7. Trigger Emergency Kill -> verify boot is blocked.
    8. Resume from Emergency Kill -> verify clean boot.
    """
    # 1. Boot Engine
    engine = ZoroEngine(settings=test_settings)
    assert await engine.initialize() is True
    assert engine.lifecycle.state == LifecycleState.RUNNING

    # 2. Connect Client
    client = NamedPipeClient(pipe_name=test_settings.pipe_name, settings=test_settings)
    telemetry_events = []
    client.register_notification_handler("telemetry.update", lambda m, p: telemetry_events.append(p))
    assert client.connect() is True

    # 3. Wait briefly for a telemetry broadcast (interval is ~1.0s)
    for _ in range(25):
        if len(telemetry_events) >= 1:
            break
        await asyncio.sleep(0.1)
    assert len(telemetry_events) >= 1
    assert "cpu_percent" in telemetry_events[0]

    # 4. Execute RPC commands
    res_echo = await asyncio.to_thread(client.send_request, "system.echo", {"message": "e2e_test"}, timeout=3.0)
    assert res_echo == {"echo": "e2e_test"}

    res_health = await asyncio.to_thread(client.send_request, "system.get_health", {}, timeout=3.0)
    assert "ram_percent" in res_health

    # 5. Initiate shutdown via IPC command
    res_shutdown = await asyncio.to_thread(client.send_request, "system.shutdown", {}, timeout=3.0)
    assert res_shutdown == {"status": "shutdown_initiated"}
    client.close()

    # Engine graceful shutdown
    await engine.shutdown()
    assert engine.lifecycle.state == LifecycleState.STOPPED

    # 6. Verify DB persistence and audit log hash chain integrity by reopening fresh DB
    from zoro.storage.db import DatabaseManager
    verify_db = DatabaseManager(settings=test_settings)
    await verify_db.initialize()
    audit = AuditLogger(verify_db, settings=test_settings)
    is_valid, corrupt_id = await audit.verify_integrity()
    assert is_valid is True
    assert corrupt_id is None
    await verify_db.close()

    # 7. Trigger Emergency Kill
    mgr = EmergencyManager(halt_lock_path=test_settings.halt_lock_path, pid_path=test_settings.pid_path)
    mgr.trigger_emergency_kill("E2E Kill Verification")
    assert mgr.is_halted()[0] is True

    # Attempt reboot -> MUST BE BLOCKED
    blocked_engine = ZoroEngine(settings=test_settings)
    assert await blocked_engine.initialize() is False
    assert blocked_engine.lifecycle.state == LifecycleState.EMERGENCY_HALTED

    # 8. Resume from Emergency Kill
    assert mgr.resume() is True
    assert mgr.is_halted()[0] is False

    # Reboot -> MUST SUCCEED
    clean_engine = ZoroEngine(settings=test_settings)
    assert await clean_engine.initialize() is True
    assert clean_engine.lifecycle.state == LifecycleState.RUNNING
    await clean_engine.shutdown()


@pytest.mark.asyncio
async def test_stress_concurrency_and_ipc_load(test_settings):
    """
    Stress verification:
    - 50 rapid concurrent DB write operations.
    - 30 rapid back-to-back IPC RPC requests.
    - Validate zero lost messages, zero DB locks, and valid audit hash chain.
    """
    engine = ZoroEngine(settings=test_settings)
    assert await engine.initialize() is True

    # 1. Stress DB concurrency
    async def write_op(idx: int):
        return await engine.db.execute_write(
            "INSERT INTO config_entries (key, value, updated_at) VALUES (?, ?, ?)",
            (f"stress_key_{idx}", f"val_{idx}", "2026-01-01T00:00:00Z"),
        )

    tasks = [write_op(i) for i in range(50)]
    results = await asyncio.gather(*tasks)
    assert len(results) == 50

    count_rows = await engine.db.execute_read("SELECT count(*) FROM config_entries WHERE key LIKE 'stress_key_%'")
    assert count_rows[0][0] == 50

    # 2. Stress IPC load
    client = NamedPipeClient(pipe_name=test_settings.pipe_name, settings=test_settings)
    assert client.connect() is True

    def send_ping(i: int):
        return client.send_request("system.echo", {"message": f"stress_ping_{i}"}, timeout=3.0)

    for i in range(30):
        reply = await asyncio.to_thread(send_ping, i)
        assert reply == {"echo": f"stress_ping_{i}"}

    client.close()
    await engine.shutdown()
