"""Controlled Windows Mouse Input Dispatcher using pywinauto and Win32."""

from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class MouseController:
    """Dispatches safe, verified mouse interactions across the desktop environment."""

    def __init__(self) -> None:
        self.is_windows = os.name == "nt"

    def move_to(self, x: int, y: int) -> bool:
        """Move mouse cursor smoothly to coordinates."""
        if not self.is_windows:
            logger.debug("Mock mouse move_to (%d, %d)", x, y)
            return True
        try:
            from pywinauto import mouse
            mouse.move(coords=(x, y))
            return True
        except Exception as e:
            logger.error("Failed to move mouse to (%d, %d): %s", x, y, e)
            return False

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> bool:
        """Execute single mouse click at current cursor location or specified coordinates."""
        if not self.is_windows:
            logger.debug("Mock mouse click %s at (%s, %s)", button, x, y)
            return True
        try:
            from pywinauto import mouse
            coords = (x, y) if x is not None and y is not None else None
            mouse.click(button=button, coords=coords)
            return True
        except Exception as e:
            logger.error("Failed to execute mouse click: %s", e)
            return False

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """Execute double mouse click."""
        if not self.is_windows:
            logger.debug("Mock mouse double_click at (%s, %s)", x, y)
            return True
        try:
            from pywinauto import mouse
            coords = (x, y) if x is not None and y is not None else None
            mouse.double_click(coords=coords)
            return True
        except Exception as e:
            logger.error("Failed to double-click: %s", e)
            return False

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """Execute right mouse click (context menu)."""
        if not self.is_windows:
            logger.debug("Mock mouse right_click at (%s, %s)", x, y)
            return True
        try:
            from pywinauto import mouse
            coords = (x, y) if x is not None and y is not None else None
            mouse.right_click(coords=coords)
            return True
        except Exception as e:
            logger.error("Failed to right-click: %s", e)
            return False

    def scroll(self, wheel_dist: int, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """Scroll vertical wheel (positive = up, negative = down)."""
        if not self.is_windows:
            logger.debug("Mock mouse scroll %d at (%s, %s)", wheel_dist, x, y)
            return True
        try:
            from pywinauto import mouse
            coords = (x, y) if x is not None and y is not None else None
            mouse.scroll(coords=coords, wheel_dist=wheel_dist)
            return True
        except Exception as e:
            logger.error("Failed to scroll mouse: %s", e)
            return False

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> bool:
        """Drag from start coordinates to end coordinates."""
        if not self.is_windows:
            logger.debug("Mock mouse drag from (%d, %d) to (%d, %d)", start_x, start_y, end_x, end_y)
            return True
        try:
            from pywinauto import mouse
            mouse.press(coords=(start_x, start_y))
            mouse.move(coords=(end_x, end_y))
            mouse.release(coords=(end_x, end_y))
            return True
        except Exception as e:
            logger.error("Failed to drag mouse: %s", e)
            return False
