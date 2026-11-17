"""Tests for emergency shutdown, handle-bound termination, and anti-PID-reuse verification."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import psutil
import pytest

from zoro.security.emergency import (
    EmergencyManager,
    get_process_creation_filetime,
    terminate_process_by_validated_handle,
)


def test_emergency_halt_and_resume(temp_dir: Path) -> None:
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


def test_kernel_sharing_lock_prevents_unauthorized_deletion(temp_dir: Path) -> None:
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


def test_emergency_correct_pid_and_matching_creation_filetime(temp_dir: Path) -> None:
    """Test 1: Correct PID and matching creation timestamp terminates cleanly via handle."""
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        mgr.record_pid(proc.pid)
        pid, ft = mgr.get_recorded_pid_info()
        assert pid == proc.pid
        assert ft is not None
        assert ft == get_process_creation_filetime(proc.pid)

        # Validate process
        is_valid, msg = mgr.validate_target_process(pid, ft)
        assert is_valid is True
        assert "validated" in msg

        # Terminate through handle-bound Win32 call
        success, term_msg = terminate_process_by_validated_handle(pid, ft, exit_code=137)
        assert success is True
        assert "terminated and reaped successfully" in term_msg

        proc.wait(timeout=5)
        assert not psutil.pid_exists(pid)
    finally:
        if proc.poll() is None:
            proc.kill()


def test_emergency_pid_reuse_rejection_protects_unrelated_process(temp_dir: Path) -> None:
    """Test 2: PID exists but creation timestamp differs (PID reuse) -> strictly refuse termination."""
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        real_pid = unrelated.pid
        real_ft = get_process_creation_filetime(real_pid)
        assert real_ft is not None

        # Simulate PID reuse: record same PID but with an obsolete/fake creation timestamp
        fake_ft = real_ft - 100_000_000_000  # 10,000 seconds earlier
        mgr.pid_path.write_text(
            f'{{"pid": {real_pid}, "creation_filetime": {fake_ft}, "recorded_at": "2026-11-15T00:00:00Z"}}',
            encoding="utf-8",
        )

        # Validation must detect PID reuse and refuse
        is_valid, msg = mgr.validate_target_process(real_pid, fake_ft)
        assert is_valid is False
        assert "PID reuse detected" in msg

        # Attempt handle-bound termination: MUST REFUSE
        success, term_msg = terminate_process_by_validated_handle(real_pid, fake_ft)
        assert success is False
        assert "PID reuse detected" in term_msg

        # Full emergency kill trigger: must skip process termination
        mgr.trigger_emergency_kill(reason="Test reuse protection")

        # Unrelated process MUST STILL BE RUNNING!
        assert psutil.pid_exists(real_pid)
        assert unrelated.poll() is None
    finally:
        unrelated.kill()
        unrelated.wait()
        mgr.resume()


def test_emergency_pid_does_not_exist(temp_dir: Path) -> None:
    """Test 3: PID does not exist -> fails safely without error."""
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    non_existent_pid = 999999
    is_valid, msg = mgr.validate_target_process(non_existent_pid, 123456789)
    assert is_valid is False
    assert "does not exist" in msg

    success, term_msg = terminate_process_by_validated_handle(non_existent_pid, 123456789)
    assert success is False
    assert "OpenProcess failed" in term_msg


def test_emergency_stale_or_malformed_pid_records(temp_dir: Path) -> None:
    """Test 4: Missing, empty, malformed, or legacy PID records."""
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
    pid, ft = mgr.get_recorded_pid_info()
    assert pid == 99999
    assert ft is None

    # 5. Legacy float create_time in JSON
    pid_path.write_text('{"pid": 1234, "create_time": 1700000000.0}', encoding="utf-8")
    pid, ft = mgr.get_recorded_pid_info()
    assert pid == 1234
    assert ft is not None
    assert ft == int((1700000000.0 + 11644473600.0) * 10000000)


def test_emergency_process_exits_between_lookup_and_open(temp_dir: Path) -> None:
    """Test 5: Process exits between PID lookup and OpenProcess."""
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    # Short-lived process that exits immediately
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    pid = proc.pid
    proc.wait()  # Guarantee it is dead
    if hasattr(proc, "_handle") and proc._handle:
        proc._handle.Close()  # Release Popen's internal kernel handle so OS frees PID

    # Attempt termination on already exited process
    success, msg = terminate_process_by_validated_handle(pid, 134000000000000000)
    assert success is False
    assert "OpenProcess failed" in msg or "PID reuse detected" in msg or "does not match" in msg


def test_emergency_pid_reuse_before_open_process(temp_dir: Path) -> None:
    """Test 6: PID reuse happens before OpenProcess (different process running under target PID)."""
    # Spawn live process B
    proc_b = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        real_ft = get_process_creation_filetime(proc_b.pid)
        assert real_ft is not None

        # Caller provides old timestamp from Process A
        old_timestamp_a = real_ft - 50_000_000_000

        # Attempt termination: OpenProcess succeeds on proc_b, but GetProcessTimes returns proc_b's timestamp
        success, msg = terminate_process_by_validated_handle(proc_b.pid, old_timestamp_a)
        assert success is False
        assert "PID reuse detected" in msg

        # Process B must remain completely unharmed
        assert psutil.pid_exists(proc_b.pid)
        assert proc_b.poll() is None
    finally:
        proc_b.kill()
        proc_b.wait()


def test_emergency_termination_through_already_validated_handle(temp_dir: Path, monkeypatch) -> None:
    """
    Test 7: The critical test - once handle is opened and creation time validated,
    termination operates on that same handle rather than resolving the PID again.
    Also verifies taskkill is never invoked.
    """
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        mgr.record_pid(proc.pid)
        pid, ft = mgr.get_recorded_pid_info()

        # Track handles passed to TerminateProcess
        from zoro.security import emergency
        k32 = emergency._get_kernel32()
        orig_terminate = k32.TerminateProcess
        orig_open = k32.OpenProcess

        opened_handles = []
        terminated_handles = []

        def tracked_open(access, inherit, p):
            h = orig_open(access, inherit, p)
            opened_handles.append(h)
            return h

        def tracked_terminate(h, code):
            terminated_handles.append(h)
            return orig_terminate(h, code)

        monkeypatch.setattr(k32, "OpenProcess", tracked_open)
        monkeypatch.setattr(k32, "TerminateProcess", tracked_terminate)

        # Assert taskkill is NEVER called via subprocess
        def forbidden_subprocess_run(*args, **kwargs):
            raise AssertionError("subprocess.run must NOT be called during handle-bound emergency kill!")

        monkeypatch.setattr(subprocess, "run", forbidden_subprocess_run)

        # Trigger emergency kill
        mgr.trigger_emergency_kill("Handle-bound test")

        # Verify that TerminateProcess received the EXACT SAME handle returned by OpenProcess
        assert len(opened_handles) == 1
        assert len(terminated_handles) == 1
        assert opened_handles[0] == terminated_handles[0]

        # Verify process is terminated
        proc.wait(timeout=5)
        assert not psutil.pid_exists(pid)
    finally:
        if proc.poll() is None:
            proc.kill()
        mgr.resume()


def test_emergency_repeated_shutdown_cycles(temp_dir: Path) -> None:
    """Test 8: Repeated emergency shutdown cycles (spawn -> kill -> resume -> verify)."""
    halt_path = temp_dir / "halt.lock"
    pid_path = temp_dir / "zoro.pid"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    for cycle in range(5):
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            mgr.record_pid(proc.pid)
            assert mgr.get_recorded_pid() == proc.pid

            mgr.trigger_emergency_kill(reason=f"Cycle {cycle} kill")
            proc.wait(timeout=5)
            assert not psutil.pid_exists(proc.pid)

            is_halted, data = mgr.is_halted()
            assert is_halted is True
            assert data["reason"] == f"Cycle {cycle} kill"

            # Resume
            assert mgr.resume() is True
            is_halted, _ = mgr.is_halted()
            assert is_halted is False
        finally:
            if proc.poll() is None:
                proc.kill()
            mgr.resume()


def test_emergency_handle_cleanup_on_all_failure_paths(temp_dir: Path, monkeypatch) -> None:
    """Test 9: Verify CloseHandle is reliably invoked on every failure path."""
    from zoro.security import emergency

    k32 = emergency._get_kernel32()
    orig_close = k32.CloseHandle
    orig_get_times = k32.GetProcessTimes
    orig_terminate = k32.TerminateProcess

    closed_handles = []

    def tracked_close(h):
        closed_handles.append(h)
        return orig_close(h)

    monkeypatch.setattr(k32, "CloseHandle", tracked_close)

    # Subtest A: GetProcessTimes fails -> handle closed
    proc_a = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        ft = get_process_creation_filetime(proc_a.pid)
        closed_handles.clear()

        monkeypatch.setattr(k32, "GetProcessTimes", lambda *args: False)
        success, msg = terminate_process_by_validated_handle(proc_a.pid, ft)
        assert success is False
        assert "GetProcessTimes failed" in msg
        assert len(closed_handles) == 1, "Handle was not closed when GetProcessTimes failed!"
    finally:
        proc_a.kill()
        proc_a.wait()

    # Subtest B: Timestamp mismatch (PID reuse) -> handle closed
    proc_b = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        monkeypatch.setattr(k32, "GetProcessTimes", orig_get_times)
        real_ft = get_process_creation_filetime(proc_b.pid)
        closed_handles.clear()

        success, msg = terminate_process_by_validated_handle(proc_b.pid, real_ft - 99999999)
        assert success is False
        assert "PID reuse detected" in msg
        assert len(closed_handles) == 1, "Handle was not closed on timestamp mismatch!"
    finally:
        proc_b.kill()
        proc_b.wait()

    # Subtest C: TerminateProcess fails -> handle closed
    proc_c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        real_ft = get_process_creation_filetime(proc_c.pid)
        closed_handles.clear()

        monkeypatch.setattr(k32, "TerminateProcess", lambda *args: False)
        success, msg = terminate_process_by_validated_handle(proc_c.pid, real_ft)
        assert success is False
        assert "TerminateProcess failed" in msg
        assert len(closed_handles) == 1, "Handle was not closed when TerminateProcess failed!"
    finally:
        monkeypatch.setattr(k32, "TerminateProcess", orig_terminate)
        proc_c.kill()
        proc_c.wait()
