"""Global Windows Emergency Keyboard Shortcut Listener.

Registers a system-wide hotkey (Ctrl + Alt + Shift + K) via the Win32 API.
Operates on a dedicated background thread with an independent Win32 message pump,
guaranteeing immediate emergency termination even if the GUI or AI engine is busy,
minimized, or unfocused.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Win32 Constants
WM_HOTKEY: int = 0x0312
WM_QUIT: int = 0x0012

# Modifiers for RegisterHotKey
MOD_ALT: int = 0x0001
MOD_CONTROL: int = 0x0002
MOD_SHIFT: int = 0x0004
MOD_WIN: int = 0x0008
MOD_NOREPEAT: int = 0x4000

# Virtual key code for 'K'
VK_K: int = 0x4B

# Default Hotkey ID
DEFAULT_HOTKEY_ID: int = 0x5A4B  # 'ZK'


class EmergencyHotkeyListener:
    """
    Independent system-wide keyboard shortcut listener for ZORO's emergency stop.
    
    Uses Windows RegisterHotKey with a NULL hWnd on a dedicated daemon thread,
    ensuring global interception across all applications without polling or hooks.
    """

    def __init__(
        self,
        on_trigger: Optional[Callable[[], None]] = None,
        hotkey_id: int = DEFAULT_HOTKEY_ID,
        vk_code: int = VK_K,
        modifiers: int = (MOD_CONTROL | MOD_ALT | MOD_SHIFT | MOD_NOREPEAT),
        shortcut_name: str = "Ctrl+Alt+Shift+K",
    ) -> None:
        self.on_trigger = on_trigger
        self.hotkey_id = hotkey_id
        self.vk_code = vk_code
        self.modifiers = modifiers
        self.shortcut_name = shortcut_name

        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._is_registered: bool = False
        self._stop_requested: bool = False
        self._started_event = threading.Event()
        self._registration_error: Optional[str] = None

    @property
    def is_registered(self) -> bool:
        """Return True if the hotkey was successfully registered with the OS."""
        return self._is_registered

    @property
    def registration_error(self) -> Optional[str]:
        """Return the error message if registration failed, or None."""
        return self._registration_error

    def start(self, timeout_sec: float = 3.0) -> bool:
        """
        Start the background listener thread and register the global hotkey.
        Returns True if registered successfully, False otherwise.
        """
        if os.name != "nt":
            self._registration_error = "Global hotkey registration requires Windows NT."
            logger.warning("Global emergency hotkey '%s' not registered: %s", self.shortcut_name, self._registration_error)
            return False

        if self._thread and self._thread.is_alive():
            logger.debug("Emergency hotkey thread already running.")
            return self._is_registered

        self._stop_requested = False
        self._started_event.clear()
        self._registration_error = None

        self._thread = threading.Thread(
            target=self._hotkey_message_loop,
            name="zoro-emergency-hotkey-listener",
            daemon=True,
        )
        self._thread.start()

        # Wait for thread to register hotkey or report error
        self._started_event.wait(timeout=timeout_sec)
        if not self._is_registered:
            logger.warning(
                "Global emergency hotkey '%s' registration failed or timed out: %s",
                self.shortcut_name,
                self._registration_error or "Timeout waiting for registration",
            )
        else:
            logger.info("Global emergency hotkey '%s' registered successfully with Windows OS.", self.shortcut_name)

        return self._is_registered

    def _hotkey_message_loop(self) -> None:
        """Dedicated thread executing the Win32 message pump."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._thread_id = kernel32.GetCurrentThreadId()

        # Force Windows to create a message queue for this thread
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        # Register system-wide hotkey
        res = user32.RegisterHotKey(None, self.hotkey_id, self.modifiers, self.vk_code)
        if not res:
            err = kernel32.GetLastError()
            self._registration_error = f"RegisterHotKey failed with WinError {err}"
            if err == 1409:
                self._registration_error += " (ERROR_HOTKEY_ALREADY_REGISTERED: Another process has registered this hotkey)"
            self._is_registered = False
            self._started_event.set()
            logger.error("Failed to register global hotkey '%s': %s", self.shortcut_name, self._registration_error)
            return

        self._is_registered = True
        self._started_event.set()

        try:
            # Standard Win32 Message Loop
            while not self._stop_requested:
                b_ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if b_ret in (0, -1):  # WM_QUIT or error
                    break

                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    logger.critical(
                        "GLOBAL EMERGENCY HOTKEY '%s' INTERCEPTED BY WINDOWS OS!",
                        self.shortcut_name,
                    )
                    self._dispatch_emergency_kill()
                    break

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            # Always unregister hotkey before thread exits
            user32.UnregisterHotKey(None, self.hotkey_id)
            self._is_registered = False
            logger.debug("Global emergency hotkey '%s' unregistered from Windows OS.", self.shortcut_name)

    def _dispatch_emergency_kill(self) -> None:
        """Trigger the emergency termination action."""
        if self.on_trigger:
            try:
                self.on_trigger()
            except Exception as e:
                logger.critical("Custom emergency callback failed: %s", e)
        else:
            # Default to EmergencyManager trigger
            from zoro.security.emergency import EmergencyManager

            mgr = EmergencyManager()
            mgr.trigger_emergency_kill(
                f"Global emergency keyboard shortcut '{self.shortcut_name}' pressed by user."
            )

    def stop(self, timeout_sec: float = 2.0) -> None:
        """Unregister the hotkey and stop the message loop thread."""
        self._stop_requested = True
        if os.name == "nt" and self._thread_id:
            import ctypes
            user32 = ctypes.windll.user32
            # Post WM_QUIT to wake GetMessageW and allow the thread to exit cleanly
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout_sec)
        
        self._is_registered = False
