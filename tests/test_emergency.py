"""Tests for emergency shutdown, halt lock management, and kernel lock behavior."""

import os
from pathlib import Path
import pytest
from zoro.security.emergency import EmergencyManager


def test_emergency_halt_and_resume(temp_dir):
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    # Initial state: not halted
    is_halted, _ = mgr.is_halted()
    assert is_halted is False
    assert mgr.get_recorded_pid() is None

    # Record and read PID
    mgr.record_pid(12345)
    assert mgr.get_recorded_pid() == 12345

    # Trigger emergency kill
    mgr.trigger_emergency_kill(reason="Test kill")
    assert halt_path.exists()
    assert mgr.get_recorded_pid() is None  # Cleared after kill
    is_halted, data = mgr.is_halted()
    assert is_halted is True
    assert data["reason"] == "Test kill"

    # Resume
    success = mgr.resume()
    assert success is True
    assert not halt_path.exists()
    is_halted, _ = mgr.is_halted()
    assert is_halted is False


def test_kernel_sharing_lock_prevents_unauthorized_deletion(temp_dir):
    """Verify that an open exclusive handle triggers WinError 32 on deletion attempts."""
    lock_file = temp_dir / "protected_halt.lock"
    lock_file.write_text("protected halt state", encoding="utf-8")

    if os.name == "nt":
        # Open with write access and no delete sharing
        fd = os.open(str(lock_file), os.O_RDWR)
        try:
            with pytest.raises(PermissionError) as exc_info:
                lock_file.unlink()
            # WinError 32: sharing violation
            assert "used by another process" in str(exc_info.value).lower() or exc_info.value.winerror == 32
        finally:
            os.close(fd)
            lock_file.unlink()
            assert not lock_file.exists()
