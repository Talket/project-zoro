"""UI Element Interactor for PROJECT ZORO.

Performs safe UI Automation actions on target elements using UI Automation patterns:
- Invoke: standard button / clickable element click
- Set Value: edit box / text input value assignment
- Toggle: checkbox / toggle switch state flipping
- Select: radio button / list item / tab item selection
- Scroll: scrolling elements / lists into view
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from zoro.computer.ui.element_inspector import UIElementInspector
from zoro.computer.ui.models import ActionType, UIActionResult, UIElementInfo, WindowRectangle

logger = logging.getLogger(__name__)


class UIElementInteractor:
    """Interacts with Windows UI elements safely via Microsoft UI Automation patterns."""

    def __init__(self, inspector: Optional[UIElementInspector] = None) -> None:
        self.inspector = inspector or UIElementInspector()

    def invoke(self, handle: int, criteria: dict[str, Any]) -> UIActionResult:
        """Invokes a clickable element (button, menu item, etc.) via InvokePattern."""
        try:
            elem = self.inspector.find_element(handle, criteria)
            if not elem:
                return UIActionResult(
                    success=False,
                    action_type=ActionType.INVOKE,
                    target_element=None,
                    error=f"Element matching {criteria} not found in window {handle}",
                )

            # Pywinauto wrapper element
            try:
                # Prefer UIA invoke pattern if available
                elem.invoke()
                return UIActionResult(
                    success=True,
                    action_type=ActionType.INVOKE,
                    target_element=self.inspector._extract_element_info(elem),
                )
            except Exception as e_invoke:
                logger.debug("UIA invoke() failed: %s, attempting click_input()", e_invoke)
                elem.click_input()
                return UIActionResult(
                    success=True,
                    action_type=ActionType.INVOKE,
                    target_element=self.inspector._extract_element_info(elem),
                )
        except Exception as e:
            logger.error("Failed to invoke element %s: %s", criteria, e)
            return UIActionResult(
                success=False,
                action_type=ActionType.INVOKE,
                target_element=None,
                error=str(e),
            )

    def set_value(self, handle: int, criteria: dict[str, Any], text: str) -> UIActionResult:
        """Sets the text or value of an input field via ValuePattern or type_keys."""
        try:
            elem = self.inspector.find_element(handle, criteria)
            if not elem:
                return UIActionResult(
                    success=False,
                    action_type=ActionType.SET_VALUE,
                    target_element=None,
                    error=f"Element matching {criteria} not found in window {handle}",
                )

            try:
                # Try set_edit_text or set_text
                if hasattr(elem, "set_edit_text"):
                    elem.set_edit_text(text)
                elif hasattr(elem, "set_text"):
                    elem.set_text(text)
                else:
                    elem.type_keys(text, with_spaces=True)
            except Exception as e_text:
                logger.debug("Direct text set failed: %s, falling back to click + type_keys", e_text)
                elem.click_input()
                elem.type_keys(f"^a{{BACKSPACE}}{text}", with_spaces=True)

            return UIActionResult(
                success=True,
                action_type=ActionType.SET_VALUE,
                target_element=self.inspector._extract_element_info(elem),
            )
        except Exception as e:
            logger.error("Failed to set value on element %s: %s", criteria, e)
            return UIActionResult(
                success=False,
                action_type=ActionType.SET_VALUE,
                target_element=None,
                error=str(e),
            )

    def toggle(self, handle: int, criteria: dict[str, Any]) -> UIActionResult:
        """Toggles a checkbox or toggle button via TogglePattern."""
        try:
            elem = self.inspector.find_element(handle, criteria)
            if not elem:
                return UIActionResult(
                    success=False,
                    action_type=ActionType.TOGGLE,
                    target_element=None,
                    error=f"Element matching {criteria} not found in window {handle}",
                )

            try:
                if hasattr(elem, "toggle"):
                    elem.toggle()
                else:
                    elem.click_input()
            except Exception as e_toggle:
                logger.debug("Toggle failed: %s, trying click_input", e_toggle)
                elem.click_input()

            return UIActionResult(
                success=True,
                action_type=ActionType.TOGGLE,
                target_element=self.inspector._extract_element_info(elem),
            )
        except Exception as e:
            logger.error("Failed to toggle element %s: %s", criteria, e)
            return UIActionResult(
                success=False,
                action_type=ActionType.TOGGLE,
                target_element=None,
                error=str(e),
            )

    def select(self, handle: int, criteria: dict[str, Any]) -> UIActionResult:
        """Selects an item (radio button, list item, tab) via SelectionItemPattern."""
        try:
            elem = self.inspector.find_element(handle, criteria)
            if not elem:
                return UIActionResult(
                    success=False,
                    action_type=ActionType.SELECT,
                    target_element=None,
                    error=f"Element matching {criteria} not found in window {handle}",
                )

            try:
                if hasattr(elem, "select"):
                    elem.select()
                else:
                    elem.click_input()
            except Exception as e_select:
                logger.debug("Select failed: %s, trying click_input", e_select)
                elem.click_input()

            return UIActionResult(
                success=True,
                action_type=ActionType.SELECT,
                target_element=self.inspector._extract_element_info(elem),
            )
        except Exception as e:
            logger.error("Failed to select element %s: %s", criteria, e)
            return UIActionResult(
                success=False,
                action_type=ActionType.SELECT,
                target_element=None,
                error=str(e),
            )
