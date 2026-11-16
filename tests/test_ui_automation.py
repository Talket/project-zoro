"""Tests for Windows UI Automation Engine in PROJECT ZORO."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest

from zoro.computer.ui.coordinate_fallback import CoordinateFallbackInteractor
from zoro.computer.ui.element_inspector import UIElementInspector
from zoro.computer.ui.element_interactor import UIElementInteractor
from zoro.computer.ui.keyboard import KeyboardController
from zoro.computer.ui.models import (
    ActionType,
    UIActionResult,
    UIElementInfo,
    VerificationResult,
    WindowInfo,
    WindowRectangle,
)
from zoro.computer.ui.mouse import MouseController
from zoro.computer.ui.verification import UIVerificationEngine
from zoro.computer.ui.window_manager import WindowManager


class TestWindowManager:
    def test_list_windows_returns_list(self):
        mgr = WindowManager()
        windows = mgr.list_windows(visible_only=False)
        assert isinstance(windows, list)

    def test_list_windows_mocked_enumeration(self):
        mgr = WindowManager()
        with patch("win32gui.EnumWindows") as mock_enum, \
             patch("win32gui.IsWindowVisible", return_value=True), \
             patch("win32gui.GetWindowText", return_value="ZORO Control Terminal"), \
             patch("win32gui.GetClassName", return_value="ConsoleWindowClass"), \
             patch("win32gui.GetWindowRect", return_value=(0, 0, 800, 600)), \
             patch("win32process.GetWindowThreadProcessId", return_value=(1, 1234)), \
             patch("psutil.Process") as mock_proc:
            
            mock_proc.return_value.name.return_value = "cmd.exe"

            # Simulate callback invocation
            def side_effect(callback, extra):
                callback(1001, None)
                callback(1002, None)
                return True

            mock_enum.side_effect = side_effect
            wins = mgr.list_windows(visible_only=True)
            assert len(wins) == 2
            assert wins[0].handle == 1001
            assert wins[0].title == "ZORO Control Terminal"
            assert wins[0].process_id == 1234
            assert wins[0].rect.width == 800

    def test_find_window(self):
        mgr = WindowManager()
        missing = mgr.find_window(title="NonExistentWindow_XYZ_987654")
        assert missing is None

    def test_window_operations_mocked(self):
        mgr = WindowManager()
        with patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.IsIconic", return_value=False), \
             patch("win32gui.SetForegroundWindow") as mock_fg, \
             patch("win32gui.BringWindowToTop") as mock_top, \
             patch("win32gui.ShowWindow") as mock_show, \
             patch("win32gui.PostMessage") as mock_post:
            
            assert mgr.focus_window(12345) is True
            assert mgr.minimize_window(12345) is True
            assert mgr.maximize_window(12345) is True
            assert mgr.restore_window(12345) is True
            assert mgr.close_window(12345) is True

    def test_window_more_operations(self):
        mgr = WindowManager()
        with patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.MoveWindow") as mock_move, \
             patch("win32process.GetWindowThreadProcessId", return_value=(0, 9999)), \
             patch("psutil.Process") as mock_proc, \
             patch("ctypes.windll.user32.IsHungAppWindow", return_value=0):

            assert mgr.move_resize_window(12345, 0, 0, 800, 600) is True
            assert mgr.is_hung(12345) is False
            assert mgr.close_window(12345, force=True) is True


class TestUIElementInspectorAndInteractor:
    def test_inspector_mocked(self):
        inspector = UIElementInspector()
        with patch.object(inspector, "inspect_window_elements") as mock_inspect:
            mock_inspect.return_value = [
                UIElementInfo(
                    element_id="btn_1",
                    name="OK",
                    control_type="Button",
                    automation_id="btn_ok",
                    is_enabled=True,
                    rect=WindowRectangle(left=10, top=10, width=50, height=25),
                )
            ]
            elems = inspector.list_elements(hwnd=100)
            assert len(elems) == 1
            assert elems[0].name == "OK"
            assert elems[0].control_type == "Button"

    def test_interactor_invoke(self):
        mock_inspector = MagicMock()
        mock_elem = MagicMock()
        mock_inspector.find_element.return_value = mock_elem
        mock_inspector._extract_element_info.return_value = UIElementInfo(
            element_id="submit_1",
            name="Submit",
            control_type="Button",
            automation_id="submit_btn",
            is_enabled=True,
        )

        interactor = UIElementInteractor(inspector=mock_inspector)
        result = interactor.invoke(handle=100, criteria={"name": "Submit"})
        assert result.success is True
        assert result.action_type == ActionType.INVOKE
        mock_elem.invoke.assert_called_once()

    def test_interactor_set_value(self):
        mock_inspector = MagicMock()
        mock_elem = MagicMock()
        mock_inspector.find_element.return_value = mock_elem
        mock_inspector._extract_element_info.return_value = UIElementInfo(
            element_id="user_1",
            name="Username",
            control_type="Edit",
            automation_id="user_input",
            is_enabled=True,
        )

        interactor = UIElementInteractor(inspector=mock_inspector)
        result = interactor.set_value(handle=100, criteria={"name": "Username"}, text="admin")
        assert result.success is True
        assert result.action_type == ActionType.SET_VALUE

    def test_interactor_element_not_found(self):
        mock_inspector = MagicMock()
        mock_inspector.find_element.return_value = None

        interactor = UIElementInteractor(inspector=mock_inspector)
        result = interactor.invoke(handle=100, criteria={"name": "Missing"})
        assert result.success is False
        assert "not found" in result.error


class TestCoordinateFallbackAndVerification:
    def test_coordinate_fallback_out_of_bounds(self):
        mouse = MagicMock()
        interactor = CoordinateFallbackInteractor(mouse_controller=mouse)
        bounds = WindowRectangle(left=0, top=0, width=100, height=100)
        res = interactor.click_at(
            x=150,
            y=50,
            expected_bounds=bounds,
            verify_fresh_screen=lambda: True,
        )
        assert res.success is False
        assert "out of expected bounds" in res.error

    def test_coordinate_fallback_stale_screen(self):
        mouse = MagicMock()
        interactor = CoordinateFallbackInteractor(mouse_controller=mouse)
        bounds = WindowRectangle(left=0, top=0, width=100, height=100)
        res = interactor.click_at(
            x=50,
            y=50,
            expected_bounds=bounds,
            verify_fresh_screen=lambda: False,
        )
        assert res.success is False
        assert "Screen state changed or stale" in res.error

    def test_coordinate_fallback_success(self):
        mouse = MagicMock()
        mouse.click.return_value = True
        interactor = CoordinateFallbackInteractor(mouse_controller=mouse)
        bounds = WindowRectangle(left=0, top=0, width=100, height=100)
        res = interactor.click_at(
            x=50,
            y=50,
            expected_bounds=bounds,
            verify_fresh_screen=lambda: True,
        )
        assert res.success is True
        assert res.action_type == "COORDINATE_CLICK"

    def test_verification_engine(self):
        mock_win_mgr = MagicMock()
        mock_inspector = MagicMock()
        engine = UIVerificationEngine(window_mgr=mock_win_mgr, inspector=mock_inspector)

        # 1. Window opened
        mock_win_mgr.find_window.return_value = WindowInfo(
            handle=999,
            title="Calculator",
            class_name="CalcFrame",
            process_id=123,
            rect=WindowRectangle(left=0, top=0, width=200, height=200),
            is_visible=True,
        )
        res = engine.verify_window_opened(title="Calculator", timeout=0.2)
        assert res.verified is True
        assert res.confidence == 1.0

        # 2. Window closed
        mock_win_mgr.list_windows.return_value = []
        res_close = engine.verify_window_closed(handle=999, timeout=0.2)
        assert res_close.verified is True
