"""Tests for lifecycle state machine and power coordinator."""

import asyncio
import pytest
from zoro.core.lifecycle import LifecycleManager, LifecycleState
from zoro.security.emergency import EmergencyManager


def test_lifecycle_transitions(temp_dir):
    mgr = EmergencyManager(halt_lock_path=temp_dir / "halt.lock")
    lifecycle = LifecycleManager(emergency_mgr=mgr)

    assert lifecycle.state == LifecycleState.UNINITIALIZED
    assert lifecycle.preflight_check() is True

    lifecycle.transition_to(LifecycleState.INITIALIZING)
    assert lifecycle.state == LifecycleState.INITIALIZING

    lifecycle.transition_to(LifecycleState.RUNNING)
    assert lifecycle.state == LifecycleState.RUNNING

    # Power suspend & resume
    lifecycle.on_suspend()
    assert lifecycle.state == LifecycleState.SUSPENDED

    lifecycle.on_resume()
    assert lifecycle.state == LifecycleState.RUNNING

    # Shutdown
    lifecycle.request_shutdown()
    assert lifecycle.state == LifecycleState.SHUTTING_DOWN


def test_lifecycle_preflight_blocks_when_halted(temp_dir):
    halt_path = temp_dir / "halt.lock"
    halt_path.write_text('{"reason": "test"}', encoding="utf-8")
    mgr = EmergencyManager(halt_lock_path=halt_path)
    lifecycle = LifecycleManager(emergency_mgr=mgr)

    assert lifecycle.preflight_check() is False
    assert lifecycle.state == LifecycleState.EMERGENCY_HALTED


@pytest.mark.asyncio
async def test_lifecycle_wait_for_shutdown_and_hooks(temp_dir):
    mgr = EmergencyManager(halt_lock_path=temp_dir / "halt.lock")
    lifecycle = LifecycleManager(emergency_mgr=mgr)
    lifecycle.setup_signal_handlers()

    hook_called = []
    lifecycle.register_shutdown_hook(lambda: hook_called.append(True))
    assert len(lifecycle._shutdown_hooks) == 1

    # Request shutdown asynchronously
    asyncio.get_event_loop().call_soon(lifecycle.request_shutdown)
    await lifecycle.wait_for_shutdown()
    assert lifecycle.state == LifecycleState.SHUTTING_DOWN


def test_lifecycle_resume_blocked_by_halt(temp_dir):
    halt_path = temp_dir / "halt.lock"
    mgr = EmergencyManager(halt_lock_path=halt_path)
    lifecycle = LifecycleManager(emergency_mgr=mgr)

    lifecycle.transition_to(LifecycleState.RUNNING)
    lifecycle.on_suspend()
    assert lifecycle.state == LifecycleState.SUSPENDED

    # Inject halt lock while suspended
    halt_path.write_text('{"reason": "Lock while asleep"}', encoding="utf-8")
    lifecycle.on_resume()
    assert lifecycle.state == LifecycleState.EMERGENCY_HALTED
