"""Controlled Windows Keyboard Input Dispatcher using pywinauto and Win32 SendInput."""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)


class KeyboardController:
    """Dispatches safe, controlled keystrokes and text entry to the active Windows interface."""

    def __init__(self) -> None:
        self.is_windows = os.name == "nt"

    def type_text(self, text: str, delay_ms: float = 10.0) -> bool:
        """Type characters sequentially into the currently focused window."""
        if not self.is_windows:
            logger.debug("Mock keyboard type_text: %s", text)
            return True

        try:
            from pywinauto.keyboard import send_keys

            # Escape pywinauto special characters { } ( ) + ^ % ~
            escaped = ""
            for char in text:
                if char in "{}+^%~()":
                    escaped += f"{{{char}}}"
                else:
                    escaped += char

            send_keys(escaped, pause=delay_ms / 1000.0, with_spaces=True, with_tabs=True, with_newlines=True)
            return True
        except Exception as e:
            logger.error("Failed to type text: %s", e)
            return False

    def send_keys(self, key_combination: str) -> bool:
        """
        Send special keystroke combinations.
        Examples:
        - '^c' -> Ctrl+C
        - '^v' -> Ctrl+V
        - '{ENTER}' -> Enter
        - '{ESC}' -> Escape
        - '%{F4}' -> Alt+F4
        - '{TAB}' -> Tab
        """
        if not self.is_windows:
            logger.debug("Mock send_keys: %s", key_combination)
            return True

        try:
            from pywinauto.keyboard import send_keys

            send_keys(key_combination)
            return True
        except Exception as e:
            logger.error("Failed to send key combination '%s': %s", key_combination, e)
            return False
