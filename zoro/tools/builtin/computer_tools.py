"""Built-in Computer Control Tools for PROJECT ZORO.

Exposes Windows UI Automation, Screen Perception, Filesystem Agent,
Controlled Shell Execution, and Application Control to the AI Orchestrator
via the Secure Tool Registry.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from zoro.computer.apps import ApplicationController, ApplicationLauncher, ApplicationRegistry
from zoro.computer.filesystem import PathSecurityValidator, SecureFilesystemAgent
from zoro.computer.filesystem.models import FileRiskTier
from zoro.computer.shell import CommandPolicy, CommandRiskTier, ControlledCommandRunner, ProcessMonitor
from zoro.computer.ui import (
    CoordinateFallbackInteractor,
    KeyboardController,
    MouseController,
    UIElementInspector,
    UIElementInteractor,
    WindowManager,
)
from zoro.computer.vision import ScreenCaptureManager, ScreenRegion, WindowsOCR
from zoro.tools.base import BaseTool, ToolContext, ToolPermissionTier

logger = logging.getLogger(__name__)


# -------------------------------------------------------------
# 1. Window Management Tools
# -------------------------------------------------------------
class WindowListInput(BaseModel):
    visible_only: bool = Field(default=True, description="Filter for only visible desktop windows")


class WindowItem(BaseModel):
    handle: int
    title: str
    class_name: str
    pid: int
    is_visible: bool


class WindowListOutput(BaseModel):
    windows: List[WindowItem]
    count: int


class WindowListTool(BaseTool):
    name = "computer_window_list"
    title = "List Windows"
    description = "Lists active top-level desktop windows on Windows."
    permission_tier = ToolPermissionTier.READ_ONLY
    input_schema = WindowListInput
    output_schema = WindowListOutput

    def __init__(self, window_mgr: Optional[WindowManager] = None) -> None:
        self.mgr = window_mgr or WindowManager()

    async def execute(self, params: WindowListInput, context: ToolContext) -> WindowListOutput:
        wins = self.mgr.list_windows(visible_only=params.visible_only)
        items = [
            WindowItem(
                handle=w.handle,
                title=w.title,
                class_name=w.class_name,
                pid=w.pid,
                is_visible=w.is_visible,
            )
            for w in wins
        ]
        return WindowListOutput(windows=items, count=len(items))


class WindowFocusInput(BaseModel):
    handle: Optional[int] = Field(default=None, description="Window handle (HWND) to focus")
    title: Optional[str] = Field(default=None, description="Window title substring to find and focus")


class WindowFocusOutput(BaseModel):
    success: bool
    focused_handle: Optional[int]
    message: str


class WindowFocusTool(BaseTool):
    name = "computer_window_focus"
    title = "Focus Window"
    description = "Brings a target window to foreground and sets input focus."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = WindowFocusInput
    output_schema = WindowFocusOutput

    def __init__(self, window_mgr: Optional[WindowManager] = None) -> None:
        self.mgr = window_mgr or WindowManager()

    async def execute(self, params: WindowFocusInput, context: ToolContext) -> WindowFocusOutput:
        hwnd = params.handle
        if not hwnd and params.title:
            win = self.mgr.find_window(title=params.title)
            if win:
                hwnd = win.handle

        if not hwnd:
            return WindowFocusOutput(success=False, focused_handle=None, message="Window not found")

        ok = self.mgr.focus_window(hwnd)
        return WindowFocusOutput(
            success=ok,
            focused_handle=hwnd if ok else None,
            message="Window focused successfully" if ok else "Failed to focus window",
        )


# -------------------------------------------------------------
# 2. Screen Perception Tools
# -------------------------------------------------------------
class ScreenCaptureInput(BaseModel):
    monitor_idx: int = Field(default=1, description="Monitor index (1=primary, 0=all)")
    window_handle: Optional[int] = Field(default=None, description="Optional window handle to capture specifically")


class ScreenCaptureOutput(BaseModel):
    image_path: str
    width: int
    height: int
    file_size_bytes: int


class ScreenCaptureTool(BaseTool):
    name = "computer_screen_capture"
    title = "Capture Screen"
    description = "Captures a high-resolution screenshot of a monitor or specific window."
    permission_tier = ToolPermissionTier.READ_ONLY
    input_schema = ScreenCaptureInput
    output_schema = ScreenCaptureOutput

    def __init__(self, capture_mgr: Optional[ScreenCaptureManager] = None) -> None:
        self.mgr = capture_mgr or ScreenCaptureManager()

    async def execute(self, params: ScreenCaptureInput, context: ToolContext) -> ScreenCaptureOutput:
        if params.window_handle:
            res = self.mgr.capture_active_window(handle=params.window_handle)
        else:
            res = self.mgr.capture_full_desktop(monitor_idx=params.monitor_idx)

        return ScreenCaptureOutput(
            image_path=str(res.image_path),
            width=res.width,
            height=res.height,
            file_size_bytes=res.file_size_bytes,
        )


class ScreenOCRInput(BaseModel):
    image_path: Optional[str] = Field(default=None, description="Path to image file; if omitted, captures active screen")


class ScreenOCROutput(BaseModel):
    full_text: str
    word_count: int
    success: bool
    error: Optional[str] = None


class ScreenOCRTool(BaseTool):
    name = "computer_screen_ocr"
    title = "Screen OCR"
    description = "Extracts visible text from a screenshot or desktop using Windows native WinRT OCR."
    permission_tier = ToolPermissionTier.READ_ONLY
    input_schema = ScreenOCRInput
    output_schema = ScreenOCROutput

    def __init__(
        self,
        capture_mgr: Optional[ScreenCaptureManager] = None,
        ocr_engine: Optional[WindowsOCR] = None,
    ) -> None:
        self.capture_mgr = capture_mgr or ScreenCaptureManager()
        self.ocr = ocr_engine or WindowsOCR()

    async def execute(self, params: ScreenOCRInput, context: ToolContext) -> ScreenOCROutput:
        if params.image_path:
            img_p = Path(params.image_path)
        else:
            cap = self.capture_mgr.capture_full_desktop()
            img_p = cap.image_path

        res = self.ocr.recognize(img_p)
        return ScreenOCROutput(
            full_text=res.full_text,
            word_count=len(res.words),
            success=res.success,
            error=res.error,
        )


# -------------------------------------------------------------
# 3. UI Element Interaction Tools
# -------------------------------------------------------------
class ElementInspectInput(BaseModel):
    window_handle: int = Field(description="Target window handle (HWND)")
    max_depth: int = Field(default=3, description="Maximum element hierarchy depth to inspect")


class ElementInspectOutput(BaseModel):
    elements_count: int
    elements: List[Dict[str, Any]]


class ElementInspectTool(BaseTool):
    name = "computer_element_inspect"
    title = "Inspect UI Elements"
    description = "Inspects UI element hierarchy of a target window via Microsoft UI Automation."
    permission_tier = ToolPermissionTier.READ_ONLY
    input_schema = ElementInspectInput
    output_schema = ElementInspectOutput

    def __init__(self, inspector: Optional[UIElementInspector] = None) -> None:
        self.inspector = inspector or UIElementInspector()

    async def execute(self, params: ElementInspectInput, context: ToolContext) -> ElementInspectOutput:
        elems = self.inspector.list_elements(params.window_handle, max_depth=params.max_depth)
        dicts = [
            {
                "name": e.name,
                "control_type": e.control_type,
                "automation_id": e.automation_id,
                "is_enabled": e.is_enabled,
                "bounding_rect": {
                    "left": e.bounding_rect.left,
                    "top": e.bounding_rect.top,
                    "width": e.bounding_rect.width,
                    "height": e.bounding_rect.height,
                }
                if e.bounding_rect
                else None,
            }
            for e in elems
        ]
        return ElementInspectOutput(elements_count=len(dicts), elements=dicts)


class ElementActionInput(BaseModel):
    window_handle: int = Field(description="Target window handle (HWND)")
    action: str = Field(description="Action to perform: 'invoke', 'set_value', 'toggle', 'select'")
    criteria: Dict[str, Any] = Field(description="Search criteria: e.g. {'name': 'Save', 'control_type': 'Button'}")
    text_value: Optional[str] = Field(default=None, description="Text value for set_value action")


class ElementActionOutput(BaseModel):
    success: bool
    action: str
    error: Optional[str] = None


class ElementActionTool(BaseTool):
    name = "computer_element_action"
    title = "Interact with UI Element"
    description = "Executes an action (invoke, set_value, toggle, select) on a UI element."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = ElementActionInput
    output_schema = ElementActionOutput

    def __init__(self, interactor: Optional[UIElementInteractor] = None) -> None:
        self.interactor = interactor or UIElementInteractor()

    async def execute(self, params: ElementActionInput, context: ToolContext) -> ElementActionOutput:
        act = params.action.lower()
        if act == "invoke":
            res = self.interactor.invoke(params.window_handle, params.criteria)
        elif act == "set_value":
            res = self.interactor.set_value(params.window_handle, params.criteria, params.text_value or "")
        elif act == "toggle":
            res = self.interactor.toggle(params.window_handle, params.criteria)
        elif act == "select":
            res = self.interactor.select(params.window_handle, params.criteria)
        else:
            return ElementActionOutput(success=False, action=params.action, error=f"Unknown action '{params.action}'")

        return ElementActionOutput(success=res.success, action=params.action, error=res.error)


# -------------------------------------------------------------
# 4. Controlled Shell Execution Tool
# -------------------------------------------------------------
class ShellExecuteInput(BaseModel):
    command: str = Field(description="Command to execute")
    timeout_seconds: Optional[float] = Field(default=30.0, description="Execution timeout in seconds")


class ShellExecuteOutput(BaseModel):
    command: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float
    risk_tier: str


class ShellExecuteTool(BaseTool):
    name = "computer_shell_execute"
    title = "Shell Execute"
    description = "Executes an approved shell command safely under policy and Job Object containment."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = ShellExecuteInput
    output_schema = ShellExecuteOutput

    def __init__(self, runner: Optional[ControlledCommandRunner] = None) -> None:
        self.runner = runner or ControlledCommandRunner()

    async def execute(self, params: ShellExecuteInput, context: ToolContext) -> ShellExecuteOutput:
        res = self.runner.execute(params.command, timeout=params.timeout_seconds)
        return ShellExecuteOutput(
            command=res.command,
            returncode=res.returncode,
            stdout=res.stdout,
            stderr=res.stderr,
            duration_seconds=round(res.duration_seconds, 3),
            risk_tier=res.risk_tier.value,
        )


# -------------------------------------------------------------
# 5. Application Control Tools
# -------------------------------------------------------------
class AppLaunchInput(BaseModel):
    app_name: str = Field(description="Application name (e.g. 'notepad', 'calc') or executable path")


class AppLaunchOutput(BaseModel):
    success: bool
    app_name: str
    pid: Optional[int]
    hwnd: Optional[int]


class AppLaunchTool(BaseTool):
    name = "computer_app_launch"
    title = "Launch Application"
    description = "Launches an application and waits for its main window."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = AppLaunchInput
    output_schema = AppLaunchOutput

    def __init__(self, launcher: Optional[ApplicationLauncher] = None) -> None:
        self.launcher = launcher or ApplicationLauncher()

    async def execute(self, params: AppLaunchInput, context: ToolContext) -> AppLaunchOutput:
        ok, pid, hwnd = self.launcher.launch(params.app_name)
        return AppLaunchOutput(
            success=ok,
            app_name=params.app_name,
            pid=pid,
            hwnd=hwnd,
        )


class AppCloseInput(BaseModel):
    app_target: str = Field(description="Application name or window title to close")
    force: bool = Field(default=False, description="Whether to forcefully terminate process")


class AppCloseOutput(BaseModel):
    success: bool
    app_target: str


class AppCloseTool(BaseTool):
    name = "computer_app_close"
    title = "Close Application"
    description = "Closes a running application gracefully or terminates if hung."
    permission_tier = ToolPermissionTier.SENSITIVE
    input_schema = AppCloseInput
    output_schema = AppCloseOutput

    def __init__(self, controller: Optional[ApplicationController] = None) -> None:
        self.controller = controller or ApplicationController()

    async def execute(self, params: AppCloseInput, context: ToolContext) -> AppCloseOutput:
        ok = self.controller.close(params.app_target, force=params.force)
        return AppCloseOutput(success=ok, app_target=params.app_target)
