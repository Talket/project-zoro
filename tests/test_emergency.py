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


def test_emergency_pid_creation_time_recording_and_validation(temp_dir):
    """Verify PID and creation timestamp recording and successful validation."""
    import psutil
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    current_pid = os.getpid()
    mgr.record_pid(current_pid)

    pid, create_time = mgr.get_recorded_pid_info()
    assert pid == current_pid
    assert create_time is not None
    assert abs(create_time - psutil.Process(current_pid).create_time()) < 0.1

    # Validate matching process
    is_valid, msg = mgr.validate_target_process(pid, create_time)
    assert is_valid is True
    assert "validated" in msg


def test_emergency_pid_reuse_rejection_protects_unrelated_process(temp_dir):
    """
    Verify that if a PID was reused by an unrelated process (mismatched creation time),
    emergency kill refuses to terminate the unrelated process.
    """
    import subprocess
    import sys
    import psutil

    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    # Spawn unrelated dummy process
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        real_pid = unrelated.pid
        real_time = psutil.Process(real_pid).create_time()

        # Simulate PID reuse: record same PID but with an obsolete/fake creation timestamp
        fake_time = real_time - 500.0
        mgr.pid_path.write_text(
            f'{{"pid": {real_pid}, "create_time": {fake_time}, "recorded_at": "2026-11-15T00:00:00Z"}}',
            encoding="utf-8",
        )

        # Validation must detect PID reuse and refuse termination
        is_valid, msg = mgr.validate_target_process(real_pid, fake_time)
        assert is_valid is False
        assert "PID reuse detected" in msg

        # Trigger emergency kill: must skip taskkill on the unrelated process
        mgr.trigger_emergency_kill(reason="Test reuse protection")

        # Unrelated process MUST STILL BE RUNNING!
        assert psutil.pid_exists(real_pid)
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait()
        mgr.resume()


def test_emergency_stale_or_malformed_pid_records(temp_dir):
    """Verify safe handling of missing, empty, malformed, or stale PID files."""
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    # 1. Missing file
    assert mgr.get_recorded_pid_info() == (None, None)

    # 2. Empty file
    pid_path.write_text("", encoding="utf-8")
    assert mgr.get_recorded_pid_info() == (None, None)

    # 3. Malformed JSON
    pid_path.write_text("{not valid json", encoding="utf-8")
    assert mgr.get_recorded_pid_info() == (None, None)

    # 4. Legacy plain integer string
    pid_path.write_text("99999", encoding="utf-8")
    pid, create_time = mgr.get_recorded_pid_info()
    assert pid == 99999
    assert create_time is None

    # 5. Stale non-existent process validation
    is_valid, msg = mgr.validate_target_process(99999, None)
    assert is_valid is False
    assert "does not exist" in msg

