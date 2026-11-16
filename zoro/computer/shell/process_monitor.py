"""Process Monitor for PROJECT ZORO.

Inspects running processes, monitors CPU/RAM usage, detects hung GUI applications
via IsHungAppWindow, and provides safe termination controls with supervisor protection.
"""

from __future__ import annotations

import ctypes
import logging
import os
from typing import Optional

import psutil

from zoro.computer.shell.models import ProcessInfo

logger = logging.getLogger(__name__)


class ProcessMonitor:
    """Monitors system processes and detects unresponsive applications."""

    def __init__(self, supervisor_pid: Optional[int] = None) -> None:
        self.supervisor_pid = supervisor_pid

    def is_hung_window(self, hwnd: int) -> bool:
        """Checks if a window handle is hung using Win32 IsHungAppWindow."""
        if os.name != "nt":
            return False
        try:
            return bool(ctypes.windll.user32.IsHungAppWindow(hwnd))
        except Exception:
            return False

    def list_processes(self, name_filter: Optional[str] = None) -> list[ProcessInfo]:
        """Lists active running processes with CPU and memory statistics."""
        results: list[ProcessInfo] = []
        filter_lower = name_filter.lower() if name_filter else None

        for proc in psutil.process_iter(["pid", "name", "status"]):
            try:
                name = proc.info["name"] or ""
                if filter_lower and filter_lower not in name.lower():
                    continue

                mem_info = proc.memory_info()
                mem_mb = mem_info.rss / (1024 * 1024)

                results.append(
                    ProcessInfo(
                        pid=proc.info["pid"],
                        name=name,
                        cpu_percent=0.0,
                        memory_mb=round(mem_mb, 2),
                        status=proc.info["status"] or "unknown",
                        is_hung=False,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return results

    def terminate_process(
        self,
        pid: int,
        force: bool = False,
        reason: str = "User requested termination",
    ) -> bool:
        """Terminates a process safely with supervisor and self protection."""
        current_pid = os.getpid()
        if pid == current_pid:
            logger.warning("Refusing to terminate self (PID %d)", pid)
            return False

        if self.supervisor_pid and pid == self.supervisor_pid:
            logger.critical("SECURITY VIOLATION: Refusing to terminate supervisor (PID %d)", pid)
            return False

        if pid <= 4:
            logger.warning("Refusing to terminate Windows kernel/system process (PID %d)", pid)
            return False

        try:
            p = psutil.Process(pid)
            if force:
                p.kill()
            else:
                p.terminate()
            p.wait(timeout=3)
            logger.info("Process PID %d terminated (%s): %s", pid, "force" if force else "graceful", reason)
            return True
        except (psutil.NoSuchProcess, psutil.TimeoutExpired) as e:
            logger.debug("Failed or process already exited for PID %d: %s", pid, e)
            return not psutil.pid_exists(pid)
        except Exception as e:
            logger.error("Error terminating process PID %d: %s", pid, e)
            return False
