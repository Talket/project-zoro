"""Tests for Computer Control Tools in Secure Tool Registry."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from zoro.computer.ui.models import WindowInfo, WindowRectangle
from zoro.tools.base import ToolContext
from zoro.tools.builtin.computer_tools import (
    AppCloseInput,
    AppCloseTool,
    AppLaunchInput,
    AppLaunchTool,
    ElementActionInput,
    ElementActionTool,
    ElementInspectInput,
    ElementInspectTool,
    ScreenCaptureInput,
    ScreenCaptureTool,
    ScreenOCRInput,
    ScreenOCRTool,
    ShellExecuteInput,
    ShellExecuteTool,
    WindowFocusInput,
    WindowFocusTool,
    WindowListInput,
    WindowListTool,
)


@pytest.mark.asyncio
async def test_window_tools():
    mock_mgr = MagicMock()
    mock_mgr.list_windows.return_value = [
        WindowInfo(
            handle=101,
            title="Editor",
            class_name="EditClass",
            process_id=202,
            rect=WindowRectangle(left=0, top=0, width=800, height=600),
            is_visible=True,
        )
    ]
    mock_mgr.focus_window.return_value = True

    # List Tool
    list_tool = WindowListTool(window_mgr=mock_mgr)
    out = await list_tool.execute(WindowListInput(visible_only=True), ToolContext())
    assert out.count == 1
    assert out.windows[0].title == "Editor"

    # Focus Tool
    focus_tool = WindowFocusTool(window_mgr=mock_mgr)
    f_out = await focus_tool.execute(WindowFocusInput(handle=101), ToolContext())
    assert f_out.success is True
    assert f_out.focused_handle == 101


@pytest.mark.asyncio
async def test_screen_tools(tmp_path: Path):
    mock_cap = MagicMock()
    img_p = tmp_path / "mock.png"
    img_p.write_bytes(b"dummy_png")

    mock_cap_res = MagicMock()
    mock_cap_res.image_path = img_p
    mock_cap_res.width = 1920
    mock_cap_res.height = 1080
    mock_cap_res.file_size_bytes = 9
    mock_cap.capture_full_desktop.return_value = mock_cap_res
    mock_cap.capture_active_window.return_value = mock_cap_res

    # Screen Capture Tool
    cap_tool = ScreenCaptureTool(capture_mgr=mock_cap)
    out = await cap_tool.execute(ScreenCaptureInput(monitor_idx=1), ToolContext())
    assert out.width == 1920
    assert out.image_path == str(img_p)

    out_win = await cap_tool.execute(ScreenCaptureInput(window_handle=101), ToolContext())
    assert out_win.width == 1920

    # Screen OCR Tool
    mock_ocr = MagicMock()
    mock_ocr_res = MagicMock()
    mock_ocr_res.full_text = "EXTRACTED TEXT"
    mock_ocr_res.words = ["W1", "W2"]
    mock_ocr_res.success = True
    mock_ocr_res.error = None
    mock_ocr.recognize.return_value = mock_ocr_res

    ocr_tool = ScreenOCRTool(capture_mgr=mock_cap, ocr_engine=mock_ocr)
    ocr_out = await ocr_tool.execute(ScreenOCRInput(image_path=str(img_p)), ToolContext())
    assert ocr_out.success is True
    assert ocr_out.full_text == "EXTRACTED TEXT"
    assert ocr_out.word_count == 2


@pytest.mark.asyncio
async def test_element_and_shell_and_app_tools():
    # Element Inspect Tool
    mock_insp = MagicMock()
    mock_insp.list_elements.return_value = []
    insp_tool = ElementInspectTool(inspector=mock_insp)
    insp_out = await insp_tool.execute(ElementInspectInput(window_handle=101), ToolContext())
    assert insp_out.elements_count == 0

    # Element Action Tool
    mock_interactor = MagicMock()
    mock_act_res = MagicMock()
    mock_act_res.success = True
    mock_act_res.error = None
    mock_interactor.invoke.return_value = mock_act_res
    mock_interactor.set_value.return_value = mock_act_res
    mock_interactor.toggle.return_value = mock_act_res
    mock_interactor.select.return_value = mock_act_res

    act_tool = ElementActionTool(interactor=mock_interactor)
    for act in ["invoke", "set_value", "toggle", "select"]:
        res = await act_tool.execute(
            ElementActionInput(window_handle=101, action=act, criteria={"name": "Btn"}, text_value="hello"),
            ToolContext(),
        )
        assert res.success is True

    # Shell Execute Tool
    mock_runner = MagicMock()
    mock_sh_res = MagicMock()
    mock_sh_res.command = "python --version"
    mock_sh_res.returncode = 0
    mock_sh_res.stdout = "Python 3.12"
    mock_sh_res.stderr = ""
    mock_sh_res.duration_seconds = 0.05
    mock_sh_res.risk_tier.value = "TIER_1_SAFE"
    mock_runner.execute.return_value = mock_sh_res

    sh_tool = ShellExecuteTool(runner=mock_runner)
    sh_out = await sh_tool.execute(ShellExecuteInput(command="python --version"), ToolContext())
    assert sh_out.returncode == 0
    assert sh_out.stdout == "Python 3.12"

    # App Launch & Close Tools
    mock_launcher = MagicMock()
    mock_launcher.launch.return_value = (True, 555, 666)
    app_launch = AppLaunchTool(launcher=mock_launcher)
    launch_out = await app_launch.execute(AppLaunchInput(app_name="notepad"), ToolContext())
    assert launch_out.success is True
    assert launch_out.pid == 555

    mock_controller = MagicMock()
    mock_controller.close.return_value = True
    app_close = AppCloseTool(controller=mock_controller)
    close_out = await app_close.execute(AppCloseInput(app_target="notepad", force=False), ToolContext())
    assert close_out.success is True
