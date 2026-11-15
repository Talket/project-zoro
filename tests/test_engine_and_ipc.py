"""Integration tests for ZoroEngine, Named Pipe IPC, Governor, and Model Gateway."""

import asyncio
import os
import pytest
from zoro.core.engine import ZoroEngine
from zoro.core.governor import ResourceGovernor
from zoro.core.health import HealthMonitor
from zoro.ipc.pipe_client import NamedPipeClient
from zoro.ipc.pipe_server import NamedPipeServer
from zoro.models.base import ChatCompletionRequest, ChatMessage
from zoro.models.mock import MockModelProvider


@pytest.mark.asyncio
async def test_mock_model_provider():
    provider = MockModelProvider(default_response="Greetings, Owner.")
    health = await provider.health_check()
    assert health.is_available is True

    caps = await provider.get_capabilities("mock-v1")
    assert caps.context_window == 4096
    assert caps.supports_tools is True

    req = ChatCompletionRequest(
        model="mock-v1",
        messages=[ChatMessage(role="user", content="Hello ZORO")],
    )
    resp = await provider.chat_completion(req)
    assert resp.content == "Greetings, Owner."
    assert resp.finish_reason == "stop"


@pytest.mark.asyncio
async def test_resource_governor(test_settings):
    monitor = HealthMonitor(settings=test_settings)
    monitor.initialize()
    governor = ResourceGovernor(monitor, settings=test_settings)

    # Acquire and release workload
    acquired = await governor.acquire_gpu_workload()
    assert acquired is True
    governor.release_gpu_workload()

    # Eviction check when not idle
    evicted = governor.check_idle_eviction()
    assert evicted is False

    monitor.close()


@pytest.mark.asyncio
async def test_engine_initialization_and_shutdown(test_settings):
    engine = ZoroEngine(settings=test_settings)
    init_success = await engine.initialize()
    assert init_success is True
    assert engine.lifecycle.state.value == "RUNNING"

    # Test RPC methods directly
    health_res = await engine._rpc_get_health({})
    assert "cpu_percent" in health_res

    state_res = await engine._rpc_get_state({})
    assert state_res["state"] == "RUNNING"

    echo_res = await engine._rpc_echo({"message": "test-ping"})
    assert echo_res["echo"] == "test-ping"

    # Clean shutdown
    await engine.shutdown()
    assert engine.lifecycle.state.value == "STOPPED"
