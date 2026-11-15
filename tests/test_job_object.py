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

        # Same-user process can open with JOB_OBJECT_TERMINATE (0x1)
        h_term = kernel32.OpenJobObjectW(0x0001, False, job_name)
        assert h_term is not None
        kernel32.CloseHandle(h_term)

        # Same-user process can open with JOB_OBJECT_ALL_ACCESS (0x1F001F)
        h_all = kernel32.OpenJobObjectW(0x1F001F, False, job_name)
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


