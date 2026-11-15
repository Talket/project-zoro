"""Tests for ZoroEngine orchestrator lifecycle, RPC handlers, and telemetry loop."""

import asyncio
import os
import pytest
from zoro.core.engine import ZoroEngine
from zoro.core.lifecycle import LifecycleState
from zoro.ipc.pipe_client import NamedPipeClient


@pytest.mark.asyncio
async def test_engine_initialization_and_shutdown(test_settings):
    """Verify engine initializes subsystems, runs telemetry loop, and shuts down cleanly."""
    engine = ZoroEngine(settings=test_settings)
    initialized = await engine.initialize()
    assert initialized is True
    assert engine.lifecycle.state == LifecycleState.RUNNING
    assert engine.emergency_mgr.get_recorded_pid() == os.getpid()

    # Verify audit event was recorded
    audit_rows = await engine.db.execute_read("SELECT action, resource FROM audit_records WHERE action='ENGINE_STARTUP'")
    assert len(audit_rows) == 1
    assert audit_rows[0][0] == "ENGINE_STARTUP"

    # Test RPC Handlers directly
    echo_res = await engine._rpc_echo({"message": "ping"})
    assert echo_res == {"echo": "ping"}

    health_res = await engine._rpc_get_health({})
    assert "cpu_percent" in health_res
    assert "ram_total_mb" in health_res

    state_res = await engine._rpc_get_state({})
    assert state_res["state"] == "RUNNING"
    assert state_res["instance_id"] == test_settings.instance_id

    audit_query_res = await engine._rpc_query_audit({"limit": 5})
    assert len(audit_query_res["records"]) >= 1

    # Connect client via IPC Named Pipe and verify end-to-end RPC
    if os.name == "nt":
        client = NamedPipeClient(pipe_name=test_settings.pipe_name, settings=test_settings)
        assert client.connect() is True
        res = await asyncio.to_thread(client.send_request, "system.echo", {"message": "ipc_live"}, timeout=3.0)
        assert res == {"echo": "ipc_live"}
        client.close()

    # Shutdown
    await engine.shutdown()
    assert engine.lifecycle.state == LifecycleState.STOPPED
    assert engine.emergency_mgr.get_recorded_pid() is None


@pytest.mark.asyncio
async def test_engine_preflight_blocks_when_halted(test_settings):
    """Verify engine refuses to initialize when an emergency halt lock exists."""
    # Place halt lock
    test_settings.halt_lock_path.parent.mkdir(parents=True, exist_ok=True)
    test_settings.halt_lock_path.write_text('{"reason": "Test halt"}', encoding="utf-8")

    engine = ZoroEngine(settings=test_settings)
    initialized = await engine.initialize()
    assert initialized is False
    assert engine.lifecycle.state != LifecycleState.RUNNING
