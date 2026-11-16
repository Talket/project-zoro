"""Tests for Controlled Shell Execution & Process Management in PROJECT ZORO."""

from __future__ import annotations

import os
import sys
from pathlib import Path
import pytest

from zoro.computer.shell.command_policy import CommandPolicy
from zoro.computer.shell.command_runner import ControlledCommandRunner
from zoro.computer.shell.models import CommandRiskTier, ProcessInfo
from zoro.computer.shell.process_monitor import ProcessMonitor


class TestCommandPolicy:
    def test_safe_read_commands(self):
        policy = CommandPolicy()
        for cmd in ["whoami", "ipconfig", "systeminfo", "python --version", "git status"]:
            tier, reason, _ = policy.evaluate_command(cmd)
            assert tier == CommandRiskTier.TIER_1_SAFE

    def test_moderate_development_commands(self):
        policy = CommandPolicy()
        tier, reason, _ = policy.evaluate_command("pytest -q")
        assert tier == CommandRiskTier.TIER_2_MODERATE

    def test_elevated_state_modifying_commands(self):
        policy = CommandPolicy()
        tier, reason, _ = policy.evaluate_command("python script_edit.py --apply")
        assert tier == CommandRiskTier.TIER_3_ELEVATED

    def test_blocked_dangerous_commands(self):
        policy = CommandPolicy()
        dangerous = [
            "format D: /fs:ntfs",
            "del /s /q c:\\",
            "Remove-Item -Recurse C:\\Windows",
            "type audit.key",
            "echo 123 > emergency.lock",
            "taskkill /f /im zoro.pid",
            ":(){ :|:& };:",
        ]
        for cmd in dangerous:
            tier, reason, _ = policy.evaluate_command(cmd)
            assert tier == CommandRiskTier.TIER_4_BLOCKED
            assert "blocked" in reason.lower()


class TestControlledCommandRunner:
    def test_execute_safe_command(self):
        runner = ControlledCommandRunner()
        res = runner.execute([sys.executable, "--version"])
        assert res.returncode == 0
        assert "Python" in res.stdout or "Python" in res.stderr
        assert res.duration_seconds > 0
        assert res.timed_out is False

    def test_execute_blocked_command_rejected(self):
        runner = ControlledCommandRunner()
        res = runner.execute("format C: /y")
        assert res.returncode == 126
        assert "blocked by security policy" in res.stderr.lower()

    def test_execute_timeout_handling(self):
        runner = ControlledCommandRunner(default_timeout=1.0)
        # Sleep for 5 seconds with a 1 second timeout
        res = runner.execute([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1.0)
        assert res.timed_out is True
        assert res.returncode == -1
        assert "timed out" in res.stderr.lower()

    def test_invalid_working_directory(self, tmp_path: Path):
        runner = ControlledCommandRunner()
        bad_dir = tmp_path / "non_existent_folder_xyz"
        res = runner.execute([sys.executable, "--version"], cwd=bad_dir)
        assert res.returncode == 1
        assert "does not exist" in res.stderr


class TestProcessMonitor:
    def test_list_processes(self):
        monitor = ProcessMonitor()
        procs = monitor.list_processes(name_filter="python")
        assert isinstance(procs, list)
        assert len(procs) > 0
        assert all(isinstance(p, ProcessInfo) for p in procs)

    def test_protection_against_terminating_self_or_supervisor(self):
        current_pid = os.getpid()
        supervisor_pid = 99999
        monitor = ProcessMonitor(supervisor_pid=supervisor_pid)

        # Self termination blocked
        assert monitor.terminate_process(current_pid) is False

        # Supervisor termination blocked
        assert monitor.terminate_process(supervisor_pid) is False

        # Kernel/system PID <= 4 blocked
        assert monitor.terminate_process(4) is False
        assert monitor.terminate_process(0) is False
