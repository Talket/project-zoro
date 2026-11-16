"""Pydantic data models for Windows UI Automation and Window Management."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WindowRectangle(BaseModel):
    """Bounding coordinates of a window or UI element."""
    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0
    width: int = 0
    height: int = 0

    def model_post_init(self, __context: Any) -> None:
        if self.right == 0 and self.width > 0:
            self.right = self.left + self.width
        if self.bottom == 0 and self.height > 0:
            self.bottom = self.top + self.height
        if self.width == 0 and self.right > self.left:
            self.width = self.right - self.left
        if self.height == 0 and self.bottom > self.top:
            self.height = self.bottom - self.top


class WindowInfo(BaseModel):
    """Metadata describing a desktop window."""
    handle: int
    title: str
    class_name: str
    process_id: int
    process_name: Optional[str] = None
    is_visible: bool = True
    is_active: bool = False
    is_hung: bool = False
    rect: WindowRectangle

    @property
    def pid(self) -> int:
        return self.process_id


class UIElementInfo(BaseModel):
    """Representation of an inspected Windows UI Automation element."""
    element_id: str = ""
    name: str
    control_type: str
    automation_id: str = ""
    class_name: str = ""
    rect: Optional[WindowRectangle] = None
    is_enabled: bool = True
    is_visible: bool = True
    value: Optional[str] = None
    supported_patterns: List[str] = Field(default_factory=list)
    children_count: int = 0


class ActionType(str, Enum):
    """Supported interactive computer control actions."""
    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    RIGHT_CLICK = "RIGHT_CLICK"
    TYPE_TEXT = "TYPE_TEXT"
    CLEAR_TEXT = "CLEAR_TEXT"
    SEND_KEYS = "SEND_KEYS"
    SELECT_DROPDOWN = "SELECT_DROPDOWN"
    TOGGLE_CHECKBOX = "TOGGLE_CHECKBOX"
    SCROLL = "SCROLL"
    COORDINATE_CLICK = "COORDINATE_CLICK"
    FOCUS_WINDOW = "FOCUS_WINDOW"
    MINIMIZE_WINDOW = "MINIMIZE_WINDOW"
    MAXIMIZE_WINDOW = "MAXIMIZE_WINDOW"
    RESTORE_WINDOW = "RESTORE_WINDOW"
    CLOSE_WINDOW = "CLOSE_WINDOW"
    INVOKE = "INVOKE"
    SET_VALUE = "SET_VALUE"
    TOGGLE = "TOGGLE"
    SELECT = "SELECT"


class VerificationResult(BaseModel):
    """Result of an independent outcome verification."""
    verified: bool
    observed_state: Dict[str, Any] = Field(default_factory=dict)
    mismatch_reason: Optional[str] = None
    expected: Optional[str] = None
    observed: Optional[str] = None
    confidence: float = 1.0


class UIActionResult(BaseModel):
    """Result of a UI action execution including post-action verification."""
    success: bool
    action_type: str = ""
    target: str = ""
    target_element: Optional[UIElementInfo] = None
    verified: bool = False
    error: Optional[str] = None
    duration_ms: float = 0.0
    verification: Optional[VerificationResult] = None
    details: Dict[str, Any] = Field(default_factory=dict)
