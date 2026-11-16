"""Application Launcher for PROJECT ZORO.

Launches desktop applications with Job Object containment and awaits
main window availability for immediate UI interaction.
"""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Optional, Union

from zoro.computer.apps.application_registry import ApplicationRegistry
from zoro.computer.ui.window_manager import WindowManager
from zoro.security.job_object import WindowsJobObject

logger = logging.getLogger(__name__)


class ApplicationLauncher:
    """Launches applications safely and tracks their primary window handle."""

    def __init__(
        self,
        registry: Optional[ApplicationRegistry] = None,
        window_mgr: Optional[WindowManager] = None,
        job_object: Optional[WindowsJobObject] = None,
    ) -> None:
        self.registry = registry or ApplicationRegistry()
        self.window_mgr = window_mgr or WindowManager()
        self.job_object = job_object

    def launch(
        self,
        app_name_or_path: Union[str, Path],
        args: Optional[list[str]] = None,
        await_window_seconds: float = 5.0,
    ) -> tuple[bool, Optional[int], Optional[int]]:
        """Launches an application and waits for its main window.

        Returns (success, pid, hwnd).
        """
        # 1. Resolve executable
        p = Path(app_name_or_path)
        if p.exists() and p.is_file():
            exe_path = p
        else:
            app_info = self.registry.find_app(str(app_name_or_path))
            if not app_info or not app_info.executable_path:
                logger.error("Application '%s' not found or has no executable path", app_name_or_path)
                return False, None, None
            exe_path = app_info.executable_path

        # 2. Build command
        cmd = [str(exe_path)] + (args or [])

        # 3. Spawn process
        try:
            proc = subprocess.Popen(cmd, shell=False)
            pid = proc.pid

            # Contain within Job Object
            if self.job_object and self.job_object.handle:
                try:
                    self.job_object.assign_process(pid)
                except Exception as e_job:
                    logger.debug("Could not assign launched app pid %d to job: %s", pid, e_job)

            # 4. Await main window
            hwnd: Optional[int] = None
            start_time = time.time()
            while time.time() - start_time < await_window_seconds:
                windows = self.window_mgr.list_windows()
                for w in windows:
                    if w.pid == pid and w.is_visible:
                        hwnd = w.handle
                        break
                if hwnd is not None:
                    break
                time.sleep(0.2)

            return True, pid, hwnd
        except Exception as e:
            logger.error("Failed to launch application %s: %s", app_name_or_path, e)
            return False, None, None
