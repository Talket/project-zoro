"""Tests for System-Wide Emergency Keyboard Shortcut (Ctrl+Alt+Shift+K)."""

from __future__ import annotations

import os
import sys
import threading
import time
import pytest
from unittest.mock import MagicMock, patch

from zoro.security.emergency_hotkey import (
    EmergencyHotkeyListener,
    DEFAULT_HOTKEY_ID,
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_NOREPEAT,
    VK_K,
    WM_HOTKEY,
)


@pytest.mark.skipif(os.name != "nt", reason="Global hotkey tests require Windows NT")
class TestEmergencyHotkeyWin32:
    """Test suite verifying Win32 global hotkey functionality on Windows 11."""

    VK_TEST = 0x86  # VK_F23: test-dedicated virtual key code to avoid colliding with active ZORO instance

    def test_hotkey_lifecycle_registration_and_unregistration(self) -> None:
        """Verify listener registers hotkey with Windows OS and unregisters cleanly on stop()."""
        callback = MagicMock()
        # Use unique hotkey ID and test VK code to avoid collision with running ZORO instance
        test_hotkey_id = 0x5A4C
        listener = EmergencyHotkeyListener(on_trigger=callback, hotkey_id=test_hotkey_id, vk_code=self.VK_TEST)

        try:
            success = listener.start(timeout_sec=3.0)
            assert success is True
            assert listener.is_registered is True
            assert listener.registration_error is None
        finally:
            listener.stop(timeout_sec=2.0)
            assert listener.is_registered is False

    def test_hotkey_dispatch_triggers_callback(self) -> None:
        """Verify that receiving WM_HOTKEY message dispatches callback immediately."""
        import ctypes
        user32 = ctypes.windll.user32

        triggered_event = threading.Event()

        def test_callback() -> None:
            triggered_event.set()

        test_hotkey_id = 0x5A4D
        listener = EmergencyHotkeyListener(on_trigger=test_callback, hotkey_id=test_hotkey_id, vk_code=self.VK_TEST)

        try:
            assert listener.start(timeout_sec=3.0) is True
            assert listener._thread_id is not None

            # Post synthetic WM_HOTKEY to the listener thread message queue
            posted = user32.PostThreadMessageW(listener._thread_id, WM_HOTKEY, test_hotkey_id, 0)
            assert posted != 0

            # Wait for callback invocation
            assert triggered_event.wait(timeout=2.0) is True
        finally:
            listener.stop(timeout_sec=2.0)

    def test_duplicate_registration_error_detection(self) -> None:
        """Verify that attempting to register an already-bound hotkey detects failure and logs error."""
        test_hotkey_id_1 = 0x5A4E
        test_hotkey_id_2 = 0x5A4F

        # Listener 1 grabs the test hotkey
        listener_1 = EmergencyHotkeyListener(hotkey_id=test_hotkey_id_1, vk_code=self.VK_TEST)
        # Listener 2 tries to grab the exact same VK + modifiers
        listener_2 = EmergencyHotkeyListener(hotkey_id=test_hotkey_id_2, vk_code=self.VK_TEST)

        try:
            res_1 = listener_1.start(timeout_sec=3.0)
            assert res_1 is True

            res_2 = listener_2.start(timeout_sec=3.0)
            assert res_2 is False
            assert listener_2.is_registered is False
            assert listener_2.registration_error is not None
            assert "1409" in listener_2.registration_error or "RegisterHotKey failed" in listener_2.registration_error
        finally:
            listener_1.stop(timeout_sec=2.0)
            listener_2.stop(timeout_sec=2.0)

    def test_non_windows_fallback(self) -> None:
        """Verify graceful fallback on non-Windows platforms."""
        listener = EmergencyHotkeyListener()
        with patch("os.name", "posix"):
            res = listener.start()
            assert res is False
            assert "Windows NT" in str(listener.registration_error)


class TestEmergencyHotkeyIntegration:
    """Verify integration with EmergencyManager and Qt UI."""

    def test_emergency_manager_triggered_by_default(self) -> None:
        """Verify default handler invokes EmergencyManager.trigger_emergency_kill."""
        listener = EmergencyHotkeyListener(on_trigger=None)
        with patch("zoro.security.emergency.EmergencyManager.trigger_emergency_kill") as mock_kill:
            listener._dispatch_emergency_kill()
            mock_kill.assert_called_once()
            assert "Ctrl+Alt+Shift+K" in mock_kill.call_args[0][0]

    def test_ui_shortcut_registered(self) -> None:
        """Verify that ZoroMainWindow configures in-focus QShortcut fallback."""
        from PySide6.QtWidgets import QApplication
        from zoro.ui.window import ZoroMainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        window = ZoroMainWindow()
        try:
            assert hasattr(window, "shortcut_emergency")
            assert window.shortcut_emergency.key().toString() == "Ctrl+Alt+Shift+K"
            assert hasattr(window, "emergency_trigger_signal")
        finally:
            window.close()
