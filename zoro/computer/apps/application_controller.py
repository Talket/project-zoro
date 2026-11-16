"""Application Controller for PROJECT ZORO.

Provides high-level lifecycle control of running applications:
focus, minimize, maximize, restore, close, and terminate.
"""

from __future__ import annotations

import logging
from typing import Optional, Union

import psutil

from zoro.computer.shell.process_monitor import ProcessMonitor
from zoro.computer.ui.window_manager import WindowManager

logger = logging.getLogger(__name__)


class ApplicationController:
    """Controls window focus, layout, and lifecycle for running desktop applications."""

    def __init__(
        self,
        window_mgr: Optional[WindowManager] = None,
        process_monitor: Optional[ProcessMonitor] = None,
    ) -> None:
        self.window_mgr = window_mgr or WindowManager()
        self.process_monitor = process_monitor or ProcessMonitor()

    def _resolve_hwnd(self, app_target: Union[str, int]) -> Optional[int]:
        """Resolves an app name or PID to a window handle."""
        if isinstance(app_target, int):
            # Target is PID or HWND
            windows = self.window_mgr.list_windows()
            # First check if it matches an HWND directly
            for w in windows:
                if w.handle == app_target:
                    return w.handle
            # Then check if it matches a PID
            for w in windows:
                if w.pid == app_target:
                    return w.handle
            return None

        # Target is a name or title
        w = self.window_mgr.find_window(title=app_target)
        if w:
            return w.handle

        # Search by process name
        name_lower = app_target.lower()
        for win in self.window_mgr.list_windows():
            try:
                p = psutil.Process(win.pid)
                if name_lower in p.name().lower() or name_lower in win.title.lower():
                    return win.handle
            except Exception:
                continue

        return None

    def focus(self, app_target: Union[str, int]) -> bool:
        """Brings the application's window to foreground."""
        hwnd = self._resolve_hwnd(app_target)
        if not hwnd:
            logger.warning("Could not find window for target %s", app_target)
            return False
        return self.window_mgr.focus_window(hwnd)

    def close(self, app_target: Union[str, int], force: bool = False) -> bool:
        """Closes the application gracefully or forcefully."""
        hwnd = self._resolve_hwnd(app_target)
        if hwnd:
            success = self.window_mgr.close_window(hwnd)
            if success and not force:
                return True

        # If window close failed or force requested, terminate via process monitor
        if isinstance(app_target, int):
            pid = app_target
            # If target was an hwnd, find its pid
            for w in self.window_mgr.list_windows():
                if w.handle == app_target:
                    pid = w.pid
                    break
            return self.process_monitor.terminate_process(pid, force=force)

        # Name search
        name_lower = app_target.lower()
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if name_lower in (p.info["name"] or "").lower():
                    return self.process_monitor.terminate_process(p.info["pid"], force=force)
            except Exception:
                continue

        return False

    def minimize(self, app_target: Union[str, int]) -> bool:
        hwnd = self._resolve_hwnd(app_target)
        if not hwnd:
            return False
        return self.window_mgr.minimize_window(hwnd)

    def maximize(self, app_target: Union[str, int]) -> bool:
        hwnd = self._resolve_hwnd(app_target)
        if not hwnd:
            return False
        return self.window_mgr.maximize_window(hwnd)

    def restore(self, app_target: Union[str, int]) -> bool:
        hwnd = self._resolve_hwnd(app_target)
        if not hwnd:
            return False
        return self.window_mgr.restore_window(hwnd)
