"""Tests for Application Discovery and Control in PROJECT ZORO."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from zoro.computer.apps.application_controller import ApplicationController
from zoro.computer.apps.application_launcher import ApplicationLauncher
from zoro.computer.apps.application_registry import BUILTIN_WINDOWS_APPS, ApplicationRegistry
from zoro.computer.apps.models import AppInfo
from zoro.computer.ui.models import WindowInfo, WindowRectangle


class TestApplicationRegistry:
    def test_builtin_apps_available(self):
        reg = ApplicationRegistry()
        for expected in ["notepad", "calc", "cmd", "powershell"]:
            app = reg.find_app(expected)
            assert app is not None
            assert isinstance(app, AppInfo)
            assert expected in app.name

    def test_partial_match(self):
        reg = ApplicationRegistry()
        app = reg.find_app("paint")
        assert app is not None
        assert app.name == "mspaint"

    def test_unknown_app(self):
        reg = ApplicationRegistry()
        app = reg.find_app("completely_unknown_fake_app_xyz")
        assert app is None


class TestApplicationLauncher:
    def test_launch_app_mocked(self):
        mock_reg = MagicMock()
        mock_win_mgr = MagicMock()
        mock_reg.find_app.return_value = AppInfo(
            name="notepad",
            display_name="Notepad",
            executable_path=Path(sys.executable),
        )

        # Mock list_windows returning the window for launched PID
        mock_win_mgr.list_windows.return_value = [
            WindowInfo(
                handle=777,
                title="Untitled - Notepad",
                class_name="Notepad",
                process_id=54321,
                rect=WindowRectangle(left=0, top=0, width=500, height=400),
                is_visible=True,
            )
        ]

        launcher = ApplicationLauncher(registry=mock_reg, window_mgr=mock_win_mgr)

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.pid = 54321
            mock_popen.return_value = mock_proc

            ok, pid, hwnd = launcher.launch("notepad", await_window_seconds=0.5)
            assert ok is True
            assert pid == 54321
            assert hwnd == 777


class TestApplicationController:
    def test_controller_window_and_process_actions(self):
        mock_win_mgr = MagicMock()
        mock_proc_mon = MagicMock()
        mock_win_mgr.list_windows.return_value = [
            WindowInfo(
                handle=888,
                title="Calculator",
                class_name="Calc",
                process_id=9876,
                rect=WindowRectangle(left=0, top=0, width=300, height=400),
                is_visible=True,
            )
        ]
        mock_win_mgr.focus_window.return_value = True
        mock_win_mgr.close_window.return_value = True
        mock_win_mgr.minimize_window.return_value = True
        mock_win_mgr.maximize_window.return_value = True
        mock_win_mgr.restore_window.return_value = True

        controller = ApplicationController(window_mgr=mock_win_mgr, process_monitor=mock_proc_mon)

        assert controller.focus(888) is True
        assert controller.minimize(888) is True
        assert controller.maximize(888) is True
        assert controller.restore(888) is True
        assert controller.close(888) is True
