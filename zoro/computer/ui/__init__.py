"""Windows UI Automation Engine for PROJECT ZORO."""

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

__all__ = [
    "ActionType",
    "CoordinateFallbackInteractor",
    "KeyboardController",
    "MouseController",
    "UIActionResult",
    "UIElementInfo",
    "UIElementInspector",
    "UIElementInteractor",
    "UIVerificationEngine",
    "VerificationResult",
    "WindowInfo",
    "WindowRectangle",
    "WindowManager",
]
