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

