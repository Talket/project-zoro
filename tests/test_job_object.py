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
