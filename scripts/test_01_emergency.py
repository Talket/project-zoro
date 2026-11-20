"""PROJECT ZORO — Verification Test 01: Emergency Termination & Safety Boundaries."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psutil
from zoro.security.emergency import (
    EmergencyManager,
    get_process_creation_filetime,
    terminate_process_by_validated_handle,
)
from zoro.security.job_object import WindowsJobObject


def run_test_01() -> dict:
    results = {}
    print("=" * 70)
    print("VERIFICATION TEST 01: EMERGENCY TERMINATION & KERNEL SAFETY INVARIANTS")
    print("=" * 70)

    python_exe = sys.executable

    # -------------------------------------------------------------
    # 1. Valid termination with matching creation FILETIME
    # -------------------------------------------------------------
    print("\n[Subtest 1.1] Handle-bound termination with valid kernel FILETIME...")
    proc1 = subprocess.Popen([python_exe, "-c", "import time; time.sleep(120)"])
    pid1 = proc1.pid
    time.sleep(0.1)

    ft1 = get_process_creation_filetime(pid1)
    print(f"  Disposable Process spawned: PID {pid1}, Creation FILETIME: {ft1}")
    assert ft1 is not None and ft1 > 0, "Failed to retrieve kernel creation FILETIME"

    success1, msg1 = terminate_process_by_validated_handle(pid1, expected_filetime=ft1, exit_code=137)
    time.sleep(0.2)
    is_alive1 = psutil.pid_exists(pid1) and psutil.Process(pid1).status() != psutil.STATUS_ZOMBIE
    print(f"  Termination result: Success={success1}, Message='{msg1}', Process Alive={is_alive1}")

    assert success1 is True, f"Termination failed: {msg1}"
    assert not is_alive1, f"Process {pid1} survived termination!"
    results["1.1_valid_termination"] = {
        "status": "PASS",
        "pid": pid1,
        "filetime": ft1,
        "termination_success": success1,
        "process_survived": is_alive1,
    }

    # -------------------------------------------------------------
    # 2. TOCTOU & PID Reuse Protection: Mismatched FILETIME
    # -------------------------------------------------------------
    print("\n[Subtest 1.2] PID Reuse / Timestamp Mismatch Protection (Anti-Recycle Invariant)...")
    proc2 = subprocess.Popen([python_exe, "-c", "import time; time.sleep(120)"])
    pid2 = proc2.pid
    time.sleep(0.1)

    real_ft2 = get_process_creation_filetime(pid2)
    fake_ft2 = real_ft2 + 50000000  # Intentionally mismatched timestamp (5 seconds later)
    print(f"  Disposable Process spawned: PID {pid2}, Real FILETIME: {real_ft2}, Fake FILETIME: {fake_ft2}")

    success2, msg2 = terminate_process_by_validated_handle(pid2, expected_filetime=fake_ft2, exit_code=137)
    time.sleep(0.1)
    is_alive2 = psutil.pid_exists(pid2)
    print(f"  Termination attempt result: Success={success2}, Message='{msg2}', Process Alive={is_alive2}")

    assert success2 is False, "CRITICAL DEFECT: Termination succeeded despite mismatched FILETIME!"
    assert "PID reuse detected" in msg2 or "does not match" in msg2, f"Unexpected message: {msg2}"
    assert is_alive2 is True, "Process was killed despite timestamp mismatch!"

    # Clean up proc2 cleanly
    proc2.kill()
    proc2.wait()
    results["1.2_pid_reuse_protection"] = {
        "status": "PASS",
        "pid": pid2,
        "mismatched_filetime_rejected": not success2,
        "rejection_message": msg2,
        "protected_process_survived": is_alive2,
    }

    # -------------------------------------------------------------
    # 3. Dead Process Graceful Handle Rejection
    # -------------------------------------------------------------
    print("\n[Subtest 1.3] Termination of already-exited process...")
    proc3 = subprocess.Popen([python_exe, "-c", "import sys; sys.exit(0)"])
    proc3.wait()
    pid3 = proc3.pid
    time.sleep(0.1)

    success3, msg3 = terminate_process_by_validated_handle(pid3, expected_filetime=ft1, exit_code=137)
    print(f"  Dead process termination attempt: Success={success3}, Message='{msg3}'")
    assert success3 is False, "Termination claimed success on a non-existent process!"
    results["1.3_dead_process_handling"] = {
        "status": "PASS",
        "pid": pid3,
        "graceful_rejection": not success3,
        "message": msg3,
    }

    # -------------------------------------------------------------
    # 4. Windows Job Object: Child Tree Containment & Termination
    # -------------------------------------------------------------
    print("\n[Subtest 1.4] Windows Job Object process tree termination...")
    job = WindowsJobObject(name="zoro_test_verification_job")
    created = job.create()
    assert created is True, "Failed to create Windows Job Object"

    # Spawn parent script that sleeps briefly so it can be assigned to the Job Object
    # BEFORE spawning any descendant processes (simulating the supervisor architecture).
    child_script = """
import subprocess, sys, time
time.sleep(0.5)
p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])
time.sleep(120)
"""
    parent_proc = subprocess.Popen([python_exe, "-c", child_script])
    assigned = job.assign_process(parent_proc.pid)
    print(f"  Parent PID: {parent_proc.pid}, Assigned to Job Object: {assigned}")
    assert assigned is True, "Failed to assign parent process to Job Object"

    # Allow parent to spawn its child while inside the Job Object
    time.sleep(1.5)

    # Identify children via psutil
    parent_ps = psutil.Process(parent_proc.pid)
    children = parent_ps.children(recursive=True)
    child_pids = [c.pid for c in children]
    print(f"  Discovered Job Object Child PIDs: {child_pids}")
    assert len(child_pids) > 0, "Parent failed to spawn child process within the Job Object"

    # Terminate all processes via Job Object
    term_ok = job.terminate_all(exit_code=42)
    time.sleep(0.5)

    parent_alive = psutil.pid_exists(parent_proc.pid)
    children_alive = [pid for pid in child_pids if psutil.pid_exists(pid)]
    print(f"  Job Object Terminate All: Success={term_ok}, Parent Alive={parent_alive}, Children Alive={children_alive}")

    job.close()
    assert term_ok is True, "Job Object terminate_all returned False"
    assert not parent_alive, "Parent process survived Job Object termination!"
    assert len(children_alive) == 0, f"Child processes survived Job Object termination: {children_alive}"

    results["1.4_job_object_tree_termination"] = {
        "status": "PASS",
        "parent_pid": parent_proc.pid,
        "child_pids": child_pids,
        "parent_terminated": not parent_alive,
        "all_children_terminated": len(children_alive) == 0,
    }

    # -------------------------------------------------------------
    # 5. Emergency Halt Lock & System Resumption
    # -------------------------------------------------------------
    print("\n[Subtest 1.5] Emergency Halt Lock state transition & Resumption...")
    test_sec = PROJECT_ROOT / "reports" / "verification_sec"
    test_sec.mkdir(parents=True, exist_ok=True)
    halt_lock = test_sec / "test_halt.lock"
    pid_file = test_sec / "test_zoro.pid"

    mgr = EmergencyManager(halt_lock_path=halt_lock, pid_path=pid_file)

    # Clean initial state
    if halt_lock.exists():
        halt_lock.unlink()

    is_halted_0, _ = mgr.is_halted()
    assert not is_halted_0, "Initial state should not be halted"

    # Trigger emergency halt
    mgr.trigger_emergency_kill(reason="Auditor Verification Test 01")
    is_halted_1, halt_data = mgr.is_halted()
    print(f"  Halt Triggered: is_halted={is_halted_1}, data={halt_data}")
    assert is_halted_1 is True, "System failed to report halted state after trigger!"
    assert halt_data.get("reason") == "Auditor Verification Test 01"

    # Resume from halt
    resumed = mgr.resume()
    is_halted_2, _ = mgr.is_halted()
    print(f"  Halt Resumed: resumed={resumed}, is_halted={is_halted_2}")
    assert resumed is True, "Failed to resume from halt"
    assert is_halted_2 is False, "System remained halted after resumption!"

    # Clean up test security dir
    if halt_lock.exists():
        halt_lock.unlink()
    if pid_file.exists():
        pid_file.unlink()

    results["1.5_emergency_halt_lock"] = {
        "status": "PASS",
        "halt_triggered": is_halted_1,
        "halt_data": halt_data,
        "resumption_success": resumed,
        "final_halt_state": is_halted_2,
    }

    print("\n>>> ALL SUBTESTS IN VERIFICATION TEST 01 PASSED <<<")
    return results


if __name__ == "__main__":
    res = run_test_01()
    print("\nFinal Results JSON:")
    print(json.dumps(res, indent=2))
