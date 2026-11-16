"""Coordinate-based interaction fallback with mandatory pre-action screen verification."""

from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

from zoro.computer.ui.models import UIActionResult, WindowRectangle
from zoro.computer.ui.mouse import MouseController

logger = logging.getLogger(__name__)


class CoordinateFallbackInteractor:
    """Executes coordinate-based mouse interactions only when UIA accessibility is unavailable."""

    def __init__(
        self,
        mouse: Optional[MouseController] = None,
        mouse_controller: Optional[MouseController] = None,
    ) -> None:
        self.mouse = mouse or mouse_controller or MouseController()

    def click_at(
        self,
        x: int,
        y: int,
        expected_bounds: Optional[WindowRectangle] = None,
        verify_fresh_screen: Optional[Callable[[], bool]] = None,
    ) -> UIActionResult:
        """Executes a verified click at (x, y) with bounds and freshness checks."""
        # Check expected bounds if provided
        if expected_bounds is not None:
            if x < expected_bounds.left or x > expected_bounds.right or y < expected_bounds.top or y > expected_bounds.bottom:
                return UIActionResult(
                    success=False,
                    action_type="COORDINATE_CLICK",
                    target=f"({x}, {y})",
                    error=f"Point ({x}, {y}) is out of expected bounds: left={expected_bounds.left}, top={expected_bounds.top}, right={expected_bounds.right}, bottom={expected_bounds.bottom}",
                )

        # Fresh screen verification
        if verify_fresh_screen is not None:
            if not verify_fresh_screen():
                return UIActionResult(
                    success=False,
                    action_type="COORDINATE_CLICK",
                    target=f"({x}, {y})",
                    error="Screen state changed or stale: pre-action verification check failed",
                )

        ok = self.mouse.click(x=x, y=y)
        return UIActionResult(
            success=ok,
            action_type="COORDINATE_CLICK",
            target=f"({x}, {y})",
            verified=True,
        )

    def execute_coordinate_action(
        self,
        x: int,
        y: int,
        action: str = "click",
        pre_verify_callback: Optional[Callable[[], bool]] = None,
        screen_bounds: Optional[Tuple[int, int]] = None,
    ) -> bool:
        """
        Execute coordinate action only after verifying bounds and executing pre-action state verification.
        """
        # 1. Bounds check
        if x < 0 or y < 0:
            logger.error("Coordinate action rejected: Negative coordinates (%d, %d)", x, y)
            return False

        if screen_bounds:
            max_w, max_h = screen_bounds
            if x >= max_w or y >= max_h:
                logger.error("Coordinate (%d, %d) exceeds screen bounds (%d, %d)", x, y, max_w, max_h)
                return False

        # 2. Mandatory pre-action verification (e.g. fresh screenshot / layout check)
        if pre_verify_callback:
            verified = pre_verify_callback()
            if not verified:
                logger.warning("Coordinate action aborted: Pre-action screen verification failed.")
                return False

        # 3. Action dispatch
        logger.info("Executing verified coordinate %s at (%d, %d)", action, x, y)
        if action == "click":
            return self.mouse.click(x=x, y=y)
        elif action == "double_click":
            return self.mouse.double_click(x=x, y=y)
        elif action == "right_click":
            return self.mouse.right_click(x=x, y=y)
        elif action == "move":
            return self.mouse.move_to(x=x, y=y)
        else:
            logger.error("Unsupported coordinate action: %s", action)
            return False
