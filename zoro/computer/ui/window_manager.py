"""Windows Window Management Subsystem using native Win32 APIs."""

from __future__ import annotations

import logging
import os
from typing import List, Optional
import psutil

from zoro.computer.ui.models import WindowInfo, WindowRectangle

logger = logging.getLogger(__name__)

SW_HIDE = 0
SW_NORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_RESTORE = 9
WM_CLOSE = 0x0010


class WindowManager:
    """Manages discovery, inspection, and manipulation of Windows desktop windows."""

    def __init__(self) -> None:
        self.is_windows = os.name == "nt"

    def list_windows(self, visible_only: bool = True) -> List[WindowInfo]:
        """Enumerate all top-level desktop windows."""
        if not self.is_windows:
            return []

        import win32gui
        import win32process

        active_hwnd = win32gui.GetForegroundWindow()
        windows: List[WindowInfo] = []

        def enum_callback(hwnd: int, extra: None) -> bool:
            if visible_only and not win32gui.IsWindowVisible(hwnd):
                return True

            title = win32gui.GetWindowText(hwnd).strip()
            if visible_only and not title:
                return True

            class_name = win32gui.GetClassName(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            left, top, right, bottom = rect
            width = max(0, right - left)
            height = max(0, bottom - top)

            if visible_only and (width == 0 or height == 0):
                return True

            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            proc_name = None
            if pid > 0:
                try:
                    proc_name = psutil.Process(pid).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    proc_name = None

            is_hung = self.is_hung(hwnd)

            windows.append(
                WindowInfo(
                    handle=hwnd,
                    title=title,
                    class_name=class_name,
                    process_id=pid,
                    process_name=proc_name,
                    is_visible=bool(win32gui.IsWindowVisible(hwnd)),
                    is_active=(hwnd == active_hwnd),
                    is_hung=is_hung,
                    rect=WindowRectangle(
                        left=left,
                        top=top,
                        right=right,
                        bottom=bottom,
                        width=width,
                        height=height,
                    ),
                )
            )
            return True

        win32gui.EnumWindows(enum_callback, None)
        return windows

    def get_active_window(self) -> Optional[WindowInfo]:
        """Retrieve details of the currently focused/active desktop window."""
        if not self.is_windows:
            return None

        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd or not win32gui.IsWindow(hwnd):
            return None

        title = win32gui.GetWindowText(hwnd).strip()
        class_name = win32gui.GetClassName(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        left, top, right, bottom = rect
        _, pid = win32process.GetWindowThreadProcessId(hwnd)

        proc_name = None
        if pid > 0:
            try:
                proc_name = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                proc_name = None

        return WindowInfo(
            handle=hwnd,
            title=title,
            class_name=class_name,
            process_id=pid,
            process_name=proc_name,
            is_visible=bool(win32gui.IsWindowVisible(hwnd)),
            is_active=True,
            is_hung=self.is_hung(hwnd),
            rect=WindowRectangle(
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                width=max(0, right - left),
                height=max(0, bottom - top),
            ),
        )

    def find_window(
        self,
        title_contains: Optional[str] = None,
        process_name: Optional[str] = None,
        handle: Optional[int] = None,
        title: Optional[str] = None,
        class_name: Optional[str] = None,
    ) -> Optional[WindowInfo]:
        """Find the best-matching window given title, process name, or handle."""
        windows = self.list_windows(visible_only=True)

        if handle is not None:
            for w in windows:
                if w.handle == handle:
                    return w

        query = (title or title_contains or "").lower()
        if query:
            for w in windows:
                if query in w.title.lower():
                    return w

        if class_name:
            c_query = class_name.lower()
            for w in windows:
                if c_query in w.class_name.lower():
                    return w

        if process_name:
            p_query = process_name.lower().replace(".exe", "")
            for w in windows:
                if w.process_name and p_query in w.process_name.lower():
                    return w

        return None

    def focus_window(self, hwnd: int) -> bool:
        """Bring window to foreground and give it input focus."""
        if not self.is_windows:
            return False

        import win32gui

        if not win32gui.IsWindow(hwnd):
            logger.warning("Cannot focus invalid window handle %s", hwnd)
            return False

        try:
            # If minimized, restore first
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, SW_RESTORE)

            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
            return True
        except Exception as e:
            logger.error("Failed to focus window %s: %s", hwnd, e)
            return False

    def minimize_window(self, hwnd: int) -> bool:
        if not self.is_windows:
            return False
        import win32gui
        if not win32gui.IsWindow(hwnd):
            return False
        win32gui.ShowWindow(hwnd, SW_SHOWMINIMIZED)
        return True

    def maximize_window(self, hwnd: int) -> bool:
        if not self.is_windows:
            return False
        import win32gui
        if not win32gui.IsWindow(hwnd):
            return False
        win32gui.ShowWindow(hwnd, SW_MAXIMIZE)
        return True

    def restore_window(self, hwnd: int) -> bool:
        if not self.is_windows:
            return False
        import win32gui
        if not win32gui.IsWindow(hwnd):
            return False
        win32gui.ShowWindow(hwnd, SW_RESTORE)
        return True

    def close_window(self, hwnd: int, force: bool = False) -> bool:
        """Close window gracefully via WM_CLOSE or force process kill."""
        if not self.is_windows:
            return False
        import win32gui
        import win32process
        import win32con

        if not win32gui.IsWindow(hwnd):
            return True

        if not force:
            win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)
            return True

        # Force termination of owning process
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if pid > 0:
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                return True
            except Exception as e:
                logger.error("Failed to force close window process %d: %s", pid, e)
                return False
        return False

    def move_resize_window(self, hwnd: int, left: int, top: int, width: int, height: int) -> bool:
        """Reposition and resize a window."""
        if not self.is_windows:
            return False
        import win32gui
        if not win32gui.IsWindow(hwnd):
            return False
        try:
            win32gui.MoveWindow(hwnd, left, top, width, height, True)
            return True
        except Exception as e:
            logger.error("Failed to move/resize window %s: %s", hwnd, e)
            return False

    def is_hung(self, hwnd: int) -> bool:
        """Check if an application window is unresponsive using user32.IsHungAppWindow."""
        if not self.is_windows:
            return False
        import ctypes
        try:
            return bool(ctypes.windll.user32.IsHungAppWindow(hwnd))
        except Exception:
            return False
