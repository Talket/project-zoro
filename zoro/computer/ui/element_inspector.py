"""Windows UI Automation Element Inspector using native UIA and pywinauto."""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from zoro.computer.ui.models import UIElementInfo, WindowRectangle

logger = logging.getLogger(__name__)


class UIElementInspector:
    """Inspects accessibility trees and UI elements using Windows UI Automation (UIA)."""

    def __init__(self) -> None:
        self.is_windows = os.name == "nt"

    def inspect_window_elements(
        self,
        hwnd: int,
        max_depth: int = 3,
        interactive_only: bool = True,
    ) -> List[UIElementInfo]:
        """Inspect the accessible UI element hierarchy of a target window."""
        if not self.is_windows:
            return []

        try:
            from pywinauto import Application

            app = Application(backend="uia").connect(handle=hwnd)
            win = app.window(handle=hwnd)
            return self._extract_elements(win, max_depth=max_depth, interactive_only=interactive_only)
        except Exception as e:
            logger.warning("UIA window inspection failed for handle %s: %s", hwnd, e)
            return []

    def list_elements(
        self,
        hwnd: int,
        max_depth: int = 3,
        interactive_only: bool = False,
    ) -> List[UIElementInfo]:
        """Convenience alias for inspect_window_elements."""
        return self.inspect_window_elements(hwnd, max_depth=max_depth, interactive_only=interactive_only)

    def find_element(
        self,
        hwnd: int,
        criteria: Optional[Dict[str, Any]] = None,
        name: Optional[str] = None,
        control_type: Optional[str] = None,
        automation_id: Optional[str] = None,
    ) -> Optional[Any]:
        """Search for a specific UI element within a window, accepting dict criteria or kwargs."""
        if criteria:
            name = name or criteria.get("name")
            control_type = control_type or criteria.get("control_type")
            automation_id = automation_id or criteria.get("automation_id")

        elements = self.inspect_window_elements(hwnd, max_depth=5, interactive_only=False)

        for el in elements:
            if automation_id and el.automation_id == automation_id:
                return el
            if name and control_type:
                if name.lower() in el.name.lower() and el.control_type.lower() == control_type.lower():
                    return el
            elif name and name.lower() in el.name.lower():
                return el
            elif control_type and el.control_type.lower() == control_type.lower():
                return el

        return None

    def _extract_elements(
        self,
        wrapper: Any,
        depth: int = 0,
        max_depth: int = 3,
        interactive_only: bool = True,
    ) -> List[UIElementInfo]:
        results: List[UIElementInfo] = []
        if depth > max_depth:
            return results

        try:
            descendants = wrapper.descendants()
        except Exception:
            return results

        INTERACTIVE_TYPES = {
            "Button",
            "Edit",
            "CheckBox",
            "RadioButton",
            "ComboBox",
            "MenuItem",
            "TabItem",
            "ListItem",
            "Hyperlink",
            "TreeItem",
            "Document",
        }

        for idx, item in enumerate(descendants):
            try:
                elem_info = item.element_info
                ctype = elem_info.control_type or "Unknown"

                if interactive_only and ctype not in INTERACTIVE_TYPES:
                    continue

                name = elem_info.name or ""
                auto_id = elem_info.automation_id or ""
                class_name = elem_info.class_name or ""
                is_enabled = getattr(item, "is_enabled", lambda: True)()
                is_visible = getattr(item, "is_visible", lambda: True)()

                rect = None
                try:
                    r = item.rectangle()
                    rect = WindowRectangle(
                        left=r.left,
                        top=r.top,
                        right=r.right,
                        bottom=r.bottom,
                        width=max(0, r.width()),
                        height=max(0, r.height()),
                    )
                except Exception:
                    pass

                # Value or text
                val = None
                try:
                    if hasattr(item, "iface_value") and item.iface_value:
                        val = item.iface_value.CurrentValue
                    elif hasattr(item, "window_text"):
                        val = item.window_text()
                except Exception:
                    val = None

                # Supported patterns
                patterns = []
                for p in ["Invoke", "Value", "Toggle", "SelectionItem", "Scroll", "ExpandCollapse"]:
                    if hasattr(item, f"iface_{p.lower()}") and getattr(item, f"iface_{p.lower()}"):
                        patterns.append(p)

                results.append(
                    UIElementInfo(
                        element_id=f"el-{depth}-{idx}-{auto_id or name[:10]}",
                        name=name,
                        control_type=ctype,
                        automation_id=auto_id,
                        class_name=class_name,
                        rect=rect,
                        is_enabled=is_enabled,
                        is_visible=is_visible,
                        value=str(val) if val is not None else None,
                        supported_patterns=patterns,
                    )
                )

                if len(results) >= 100:
                    break
            except Exception:
                continue

        return results
