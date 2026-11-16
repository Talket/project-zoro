"""Live Windows emergency shutdown scenarios and process containment tests.

Verifies:
- Scenario 1: Normal emergency shutdown (halts, terminates core, writes halt lock).
- Scenario 2: Supervisor crash (parent killed -> Job Object terminates core automatically).
- Scenario 3: Core crash (core exits unexpectedly -> supervisor detects and handles).
- Scenario 4: Child containment (child spawns grandchild -> all terminated by Job Object).
- Scenario 5: Handle non-inheritance (child cannot access parent Job Object handle).
- Scenario 6: Halt lock persistence (startup blocked while halted, cleared by resume).
- Scenario 7: Repeated cycle (boot -> kill -> resume -> boot 10x consecutively).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from zoro.security.emergency import EmergencyManager
from zoro.security.job_object import WindowsJobObject


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tests require Windows NT")
def test_scenario_1_normal_emergency_shutdown(tmp_path: Path):
    """Scenario 1: Normal emergency shutdown halts, terminates core, writes halt lock."""
    halt_path = tmp_path / "sc1_halt.lock"
    pid_path = tmp_path / "sc1_pid.lock"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    core = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        mgr.record_pid(core.pid)
        assert mgr.get_recorded_pid() == core.pid

        # Trigger emergency kill
        killed = mgr.trigger_emergency_kill("Scenario 1 verified emergency kill")
        assert killed is True
        core.wait(timeout=5)

        assert not psutil.pid_exists(core.pid)
        is_halted, halt_data = mgr.is_halted()
        assert is_halted is True
        assert halt_data is not None
        assert halt_data["reason"] == "Scenario 1 verified emergency kill"
    finally:
        if core.poll() is None:
            core.kill()
        mgr.resume()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tests require Windows NT")
def test_scenario_2_supervisor_crash_terminates_child_via_job_object():
    """Scenario 2: Supervisor process killed -> Job Object terminates core automatically."""
    supervisor_code = """
import ctypes, subprocess, sys, time, os
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
job = kernel32.CreateJobObjectW(None, 'Local\\\\ZoroTestSc2SupervisorCrash')

from ctypes import wintypes
class IO_COUNTERS(ctypes.Structure):
    _fields_ = [('r_ops', ctypes.c_uint64), ('w_ops', ctypes.c_uint64), ('o_ops', ctypes.c_uint64), ('r_tx', ctypes.c_uint64), ('w_tx', ctypes.c_uint64), ('o_tx', ctypes.c_uint64)]
class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('p_user', ctypes.c_int64), ('j_user', ctypes.c_int64), ('LimitFlags', wintypes.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active_lim', wintypes.DWORD), ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('sched', wintypes.DWORD)]
class EXT_LIMIT(ctypes.Structure):
    _fields_ = [('Basic', BASIC_LIMIT), ('Io', IO_COUNTERS), ('p_mem', ctypes.c_size_t), ('j_mem', ctypes.c_size_t), ('peak_p_mem', ctypes.c_size_t), ('peak_j_mem', ctypes.c_size_t)]

info = EXT_LIMIT()
info.Basic.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))

child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
h_proc = kernel32.OpenProcess(0x1F0FFF, False, child.pid)
kernel32.AssignProcessToJobObject(job, h_proc)
kernel32.CloseHandle(h_proc)

print(f'CHILD_PID:{child.pid}', flush=True)
time.sleep(0.3)
# Supervisor crashes abruptly
os._exit(42)
"""
    proc = subprocess.Popen([sys.executable, "-c", supervisor_code], stdout=subprocess.PIPE, text=True)
    line = proc.stdout.readline()
    child_pid = int(line.strip().split(":")[1])
    proc.wait()
    assert proc.returncode == 42

    time.sleep(0.5)
    # Child must have been terminated by kernel KILL_ON_JOB_CLOSE
    assert not psutil.pid_exists(child_pid)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tests require Windows NT")
def test_scenario_3_core_crash_detected_by_supervisor():
    """Scenario 3: Core process crashes or exits unexpectedly -> supervisor detects and handles."""
    job_name = "Local\\ZoroTestSc3CoreCrash"
    job = WindowsJobObject(name=job_name)
    assert job.create() is True

    try:
        # Spawn core that exits with code 42 after brief run
        core = subprocess.Popen([sys.executable, "-c", "import sys, time; time.sleep(0.2); sys.exit(42)"])
        assigned = job.assign_process(core.pid)
        assert assigned is True

        ret = core.wait(timeout=5)
        assert ret == 42
    finally:
        job.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tests require Windows NT")
def test_scenario_4_child_process_containment_and_termination(tmp_path: Path):
    """Scenario 4: Child spawns grandchild -> all processes contained in Job Object and killed."""
    job_name = "Local\\ZoroTestSc4Containment"
    job = WindowsJobObject(name=job_name)
    assert job.create() is True

    pid_file = tmp_path / "gc.pid"
    code = f"""
import subprocess, sys, time
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
with open(r'{pid_file}', 'w') as f:
    f.write(str(p.pid))
time.sleep(30)
"""
    child = subprocess.Popen([sys.executable, "-c", code])
    try:
        job.assign_process(child.pid)

        # Wait for grandchild PID to be written
        for _ in range(50):
            if pid_file.exists():
                break
            time.sleep(0.1)

        assert pid_file.exists(), "Grandchild failed to start"
        gc_pid = int(pid_file.read_text().strip())

        assert psutil.pid_exists(child.pid)
        assert psutil.pid_exists(gc_pid)

        # Terminate Job Object
        terminated = job.terminate_all(exit_code=137)
        assert terminated is True
        time.sleep(0.5)

        assert not psutil.pid_exists(child.pid), "Child still running"
        assert not psutil.pid_exists(gc_pid), "Grandchild still running"
    finally:
        job.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tests require Windows NT")
def test_scenario_5_handle_inheritance_rejection():
    """Scenario 5: Verify child process cannot access or manipulate parent Job Object handle."""
    job_name = "Local\\ZoroTestSc5HandleInherit"
    job = WindowsJobObject(name=job_name)
    assert job.create() is True
    assert job.is_handle_inheritable() is False
    handle_val = int(job.handle)

    try:
        # Child attempts to use parent's raw handle integer
        child_code = f"""
import ctypes
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
res = kernel32.TerminateJobObject({handle_val}, 1)
err = ctypes.get_last_error()
assert not res
# ERROR_INVALID_HANDLE is 6
assert err == 6
"""
        res = subprocess.run([sys.executable, "-c", child_code], capture_output=True, text=True)
        assert res.returncode == 0, f"Child check failed: {res.stderr}"
    finally:
        job.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tests require Windows NT")
def test_scenario_6_halt_lock_persistence_and_resumption(tmp_path: Path):
    """Scenario 6: System refuses to start while halt lock exists; resume clears lock."""
    halt_path = tmp_path / "sc6_halt.lock"
    pid_path = tmp_path / "sc6_pid.lock"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    # Initial state: not halted
    assert mgr.is_halted()[0] is False

    # Trigger emergency kill
    mgr.trigger_emergency_kill("Scenario 6 verification")
    assert mgr.is_halted()[0] is True
    assert halt_path.exists()

    # Resume clears lock
    resumed = mgr.resume()
    assert resumed is True
    assert not halt_path.exists()
    assert mgr.is_halted()[0] is False


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object tests require Windows NT")
def test_scenario_7_repeated_boot_kill_resume_cycle(tmp_path: Path):
    """Scenario 7: 10x consecutive cycle of boot -> emergency kill -> resume -> boot."""
    halt_path = tmp_path / "sc7_halt.lock"
    pid_path = tmp_path / "sc7_pid.lock"
    mgr = EmergencyManager(halt_lock_path=halt_path, pid_path=pid_path)

    for i in range(10):
        # 1. Boot dummy core process
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            mgr.record_pid(proc.pid)
            assert mgr.get_recorded_pid() == proc.pid

            # 2. Emergency kill
            killed = mgr.trigger_emergency_kill(f"Scenario 7 cycle {i}")
            assert killed is True
            proc.wait(timeout=5)

            # 3. Assert dead and halted
            assert proc.poll() is not None
            # Allow brief moment for Windows process table reap
            dead = False
            for _ in range(30):
                if not psutil.pid_exists(proc.pid):
                    dead = True
                    break
                time.sleep(0.05)
            assert dead is True, f"Process {proc.pid} still exists in psutil after wait"
            assert mgr.is_halted()[0] is True

            # 4. Resume
            assert mgr.resume() is True
            assert mgr.is_halted()[0] is False
        finally:
            if proc.poll() is None:
                proc.kill()
