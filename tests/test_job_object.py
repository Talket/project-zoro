"""Tests for Windows Job Object process containment and named termination."""

import os
import subprocess
import sys
import time
import pytest
from zoro.security.job_object import WindowsJobObject


def test_job_object_lifecycle_on_child_process():
    """Verify that a child process is contained and killed by Job Object."""
    job = WindowsJobObject(name="Local\\ZoroTestJobObjectChild")
    created = job.create()
    assert created is True

    if os.name == "nt":
        assert job.handle is not None
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            assigned = job.assign_process(child.pid)
            assert assigned is True

            job.terminate_all(exit_code=137)
            time.sleep(0.2)

            ret = child.poll()
            assert ret is not None
            assert ret == 137
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

    job.close()
    assert job.handle is None


def test_terminate_named_job_from_external_caller():
    """Verify that terminate_named_job finds an existing Job Object and terminates it."""
    job_name = "Local\\ZoroTestNamedTermination"
    job = WindowsJobObject(name=job_name)
    assert job.create() is True

    if os.name == "nt":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            job.assign_process(child.pid)

            # Terminate from classmethod by name
            terminated = WindowsJobObject.terminate_named_job(name=job_name, exit_code=143)
            assert terminated is True
            time.sleep(0.2)

            ret = child.poll()
            assert ret is not None
            assert ret == 143
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()

    job.close()


def test_job_object_kernel_limits_and_non_inheritance():
    """Verify kernel LimitFlags (KILL_ON_JOB_CLOSE, zero breakaway) and HANDLE_FLAG_INHERIT=0."""
    job_name = "Local\\ZoroTestKernelLimits"
    job = WindowsJobObject(name=job_name)
    assert job.create() is True

    try:
        if os.name == "nt":
            # 1. Handle inheritance must be FALSE (0)
            assert job.is_handle_inheritable() is False

            # 2. LimitFlags must include KILL_ON_JOB_CLOSE (0x2000)
            flags = job.query_limit_flags()
            assert flags is not None
            assert flags & 0x00002000 == 0x00002000

            # 3. Breakaway flags must NOT be set (prevent escape)
            assert flags & 0x00000800 == 0  # JOB_OBJECT_LIMIT_BREAKAWAY_OK
            assert flags & 0x00001000 == 0  # JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK
    finally:
        job.close()


def test_job_object_active_process_accounting():
    """Verify active process accounting tracks processes assigned and terminated."""
    job_name = "Local\\ZoroTestAccountingUnit"
    job = WindowsJobObject(name=job_name)
    assert job.create() is True

    try:
        if os.name == "nt":
            initial_count = job.query_active_process_count()
            assert initial_count == 0

            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            try:
                assigned = job.assign_process(child.pid)
                assert assigned is True
                assert job.query_active_process_count() >= 1

                job.terminate_all(exit_code=137)
                time.sleep(0.2)
                assert job.query_active_process_count() == 0
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
    finally:
        job.close()


def test_unnamed_job_object_default_and_non_openable():
    """Verify that default WindowsJobObject is unnamed, non-inheritable, and cannot be opened by name."""
    job = WindowsJobObject()  # default is unnamed
    assert job.name is None
    assert job.create() is True

    try:
        if os.name == "nt":
            assert job.handle is not None
            assert job.is_handle_inheritable() is False

            # open_existing with None must return None
            assert WindowsJobObject.open_existing(None) is None
            assert WindowsJobObject.terminate_named_job(None) is False

            # Win32 OpenJobObjectW with NULL fails with ERROR_INVALID_PARAMETER (87)
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenJobObjectW.restype = wintypes.HANDLE
            kernel32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
            h = kernel32.OpenJobObjectW(0x1F001F, False, None)
            err = ctypes.get_last_error()
            assert h is None
            assert err == 87
    finally:
        job.close()


def test_named_job_object_same_user_access_proof():
    """
    Demonstrate the exact security reason why named Job Objects are avoided by default:
    When a named Job Object is created with default DACL, an external same-user process
    CAN open it with QUERY, TERMINATE, and ALL_ACCESS.
    """
    if os.name != "nt":
        return

    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]

    job_name = r"Local\ZoroTestNamedProofAudit"
    job = WindowsJobObject(name=job_name)
    assert job.create() is True

    try:
        # Same-user process can open with JOB_OBJECT_QUERY (0x4)
        h_query = kernel32.OpenJobObjectW(0x0004, False, job_name)
        assert h_query is not None
        kernel32.CloseHandle(h_query)

        # Same-user process can open with JOB_OBJECT_TERMINATE (0x8)
        h_term = kernel32.OpenJobObjectW(0x0008, False, job_name)
        assert h_term is not None
        kernel32.CloseHandle(h_term)

        # Same-user process can open with modern JOB_OBJECT_ALL_ACCESS (0x1F003F)
        h_all = kernel32.OpenJobObjectW(0x1F003F, False, job_name)
        assert h_all is not None
        kernel32.CloseHandle(h_all)
    finally:
        job.close()


def test_unnamed_job_object_kill_on_close_unconditional():
    """Verify that closing the handle on an unnamed Job Object immediately terminates contained child processes."""
    if os.name != "nt":
        return

    import psutil
    job = WindowsJobObject(name=None)
    assert job.create() is True

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        assigned = job.assign_process(child.pid)
        assert assigned is True
        assert psutil.pid_exists(child.pid)

        # Close handle directly (simulates supervisor exit / crash)
        job.close()
        time.sleep(0.4)

        # Child must be terminated unconditionally
        assert not psutil.pid_exists(child.pid)
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_job_object_explicit_handle_duplication_boundary():
    """
    Empirical verification of the exact Win32 security boundary for handle duplication:
    1. An external process under the same user token CAN call OpenProcess(PROCESS_DUP_HANDLE).
    2. DuplicateHandle succeeds, transferring the unnamed Job Object handle.
    3. The retained duplicated handle keeps the Job Object reference count > 0.
    4. When the supervisor terminates, KILL_ON_JOB_CLOSE does NOT fire while the handle is retained.
    5. When the external duplicated handle is closed, KILL_ON_JOB_CLOSE terminates the child.
    """
    if os.name != "nt":
        return

    import ctypes
    from ctypes import wintypes
    import psutil

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.DuplicateHandle.restype = wintypes.BOOL
    kernel32.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD
    ]

    PROCESS_DUP_HANDLE = 0x0040
    DUPLICATE_SAME_ACCESS = 0x00000002

    # Supervisor code creates unnamed job, assigns child, reports PID and handle
    supervisor_code = """
import ctypes, subprocess, sys, time, os
from ctypes import wintypes
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]

job = kernel32.CreateJobObjectW(None, None)

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [('r_ops', ctypes.c_uint64), ('w_ops', ctypes.c_uint64), ('o_ops', ctypes.c_uint64), ('r_tx', ctypes.c_uint64), ('w_tx', ctypes.c_uint64), ('o_tx', ctypes.c_uint64)]
class BASIC_LIMIT(ctypes.Structure):
    _fields_ = [('p_user', ctypes.c_int64), ('j_user', ctypes.c_int64), ('LimitFlags', wintypes.DWORD), ('min_ws', ctypes.c_size_t), ('max_ws', ctypes.c_size_t), ('active_lim', wintypes.DWORD), ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD), ('sched', wintypes.DWORD)]
class EXT_LIMIT(ctypes.Structure):
    _fields_ = [('Basic', BASIC_LIMIT), ('Io', IO_COUNTERS), ('p_mem', ctypes.c_size_t), ('j_mem', ctypes.c_size_t), ('peak_p_mem', ctypes.c_size_t), ('peak_j_mem', ctypes.c_size_t)]

info = EXT_LIMIT()
info.Basic.LimitFlags = 0x2000
kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))

child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
h_proc = kernel32.OpenProcess(0x1F0FFF, False, child.pid)
kernel32.AssignProcessToJobObject(job, h_proc)
kernel32.CloseHandle(h_proc)

print(f'SUP:{os.getpid()}:JOB:{int(job)}:CHILD:{child.pid}', flush=True)

while True:
    time.sleep(0.1)
"""

    sup = subprocess.Popen([sys.executable, "-c", supervisor_code], stdout=subprocess.PIPE, text=True)
    try:
        line = sup.stdout.readline().strip()
        parts = line.split(":")
        sup_pid = int(parts[1])
        job_val = int(parts[3])
        child_pid = int(parts[5])

        # Step 1: OpenProcess with PROCESS_DUP_HANDLE
        h_sup_proc = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, sup_pid)
        assert h_sup_proc is not None and h_sup_proc != 0

        # Step 2: DuplicateHandle into current process
        h_dup = wintypes.HANDLE()
        dup_success = kernel32.DuplicateHandle(
            h_sup_proc,
            wintypes.HANDLE(job_val),
            kernel32.GetCurrentProcess(),
            ctypes.byref(h_dup),
            0,
            False,
            DUPLICATE_SAME_ACCESS,
        )
        assert bool(dup_success) is True
        assert h_dup.value is not None

        # Step 3: Terminate supervisor while retaining duplicated handle
        sup.terminate()
        sup.wait(timeout=5)

        time.sleep(0.4)
        # Child MUST be alive because h_dup is still holding the job object open!
        assert psutil.pid_exists(child_pid)

        # Step 4: Close the duplicated handle
        kernel32.CloseHandle(h_dup)
        time.sleep(0.4)

        # Now that the LAST handle is closed, child MUST be terminated!
        assert not psutil.pid_exists(child_pid)
        kernel32.CloseHandle(h_sup_proc)
    finally:
        if sup.poll() is None:
            sup.kill()
        if psutil.pid_exists(child_pid):
            try:
                psutil.Process(child_pid).kill()
            except Exception:
                pass


