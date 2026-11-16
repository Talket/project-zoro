"""Verification Engine for PROJECT ZORO.

Implements the Observe-Act-Verify loop for UI Automation.
Ensures actions are empirically verified through post-action observations
rather than assuming success from API return codes.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from zoro.computer.ui.element_inspector import UIElementInspector
from zoro.computer.ui.models import VerificationResult
from zoro.computer.ui.window_manager import WindowManager

logger = logging.getLogger(__name__)


class UIVerificationEngine:
    """Verifies UI automation outcomes by polling UI state until satisfied or timed out."""

    def __init__(
        self,
        window_mgr: Optional[WindowManager] = None,
        inspector: Optional[UIElementInspector] = None,
    ) -> None:
        self.window_mgr = window_mgr or WindowManager()
        self.inspector = inspector or UIElementInspector()

    def verify_window_opened(
        self,
        title: Optional[str] = None,
        class_name: Optional[str] = None,
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> VerificationResult:
        """Verifies that a window matching title or class_name appears."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            win = self.window_mgr.find_window(title=title, class_name=class_name)
            if win is not None:
                return VerificationResult(
                    verified=True,
                    expected=f"Window with title '{title}' or class '{class_name}' opened",
                    observed=f"Found window HWND {win.handle}: '{win.title}' ({win.class_name})",
                    confidence=1.0,
                )
            time.sleep(poll_interval)

        return VerificationResult(
            verified=False,
            expected=f"Window with title '{title}' or class '{class_name}' opened",
            observed="Window not found within timeout",
            confidence=0.0,
        )

    def verify_window_closed(
        self,
        handle: int,
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> VerificationResult:
        """Verifies that a window with handle `handle` is closed/gone."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            windows = self.window_mgr.list_windows()
            if not any(w.handle == handle for w in windows):
                return VerificationResult(
                    verified=True,
                    expected=f"Window HWND {handle} closed",
                    observed=f"Window HWND {handle} no longer present",
                    confidence=1.0,
                )
            time.sleep(poll_interval)

        return VerificationResult(
            verified=False,
            expected=f"Window HWND {handle} closed",
            observed=f"Window HWND {handle} is still active",
            confidence=0.0,
        )

    def verify_element_text(
        self,
        handle: int,
        criteria: dict[str, Any],
        expected_text: str,
        exact: bool = False,
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> VerificationResult:
        """Verifies that an element's text matches expected text."""
        start_time = time.time()
        last_observed = None

        while time.time() - start_time < timeout:
            elem = self.inspector.find_element(handle, criteria)
            if elem:
                info = self.inspector._extract_element_info(elem)
                actual_text = info.name or ""
                last_observed = actual_text
                match = (actual_text == expected_text) if exact else (expected_text.lower() in actual_text.lower())
                if match:
                    return VerificationResult(
                        verified=True,
                        expected=f"Element text {'==' if exact else 'contains'} '{expected_text}'",
                        observed=f"Element text is '{actual_text}'",
                        confidence=1.0,
                    )
            time.sleep(poll_interval)

        return VerificationResult(
            verified=False,
            expected=f"Element text {'==' if exact else 'contains'} '{expected_text}'",
            observed=f"Last observed text: '{last_observed}'",
            confidence=0.0,
        )

    def verify_element_exists(
        self,
        handle: int,
        criteria: dict[str, Any],
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> VerificationResult:
        """Verifies that an element exists matching criteria."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            elem = self.inspector.find_element(handle, criteria)
            if elem is not None:
                info = self.inspector._extract_element_info(elem)
                return VerificationResult(
                    verified=True,
                    expected=f"Element matching {criteria} exists",
                    observed=f"Found element '{info.name}' ({info.control_type})",
                    confidence=1.0,
                )
            time.sleep(poll_interval)

        return VerificationResult(
            verified=False,
            expected=f"Element matching {criteria} exists",
            observed="Element not found within timeout",
            confidence=0.0,
        )

    def verify_element_vanished(
        self,
        handle: int,
        criteria: dict[str, Any],
        timeout: float = 3.0,
        poll_interval: float = 0.2,
    ) -> VerificationResult:
        """Verifies that an element is no longer present."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            elem = self.inspector.find_element(handle, criteria)
            if elem is None:
                return VerificationResult(
                    verified=True,
                    expected=f"Element matching {criteria} vanishes",
                    observed="Element is absent",
                    confidence=1.0,
                )
            time.sleep(poll_interval)

        return VerificationResult(
            verified=False,
            expected=f"Element matching {criteria} vanishes",
            observed="Element is still present",
            confidence=0.0,
        )
