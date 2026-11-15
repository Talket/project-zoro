"""Tests for PySide6 Desktop HUD, System Tray, and UI Application."""

import os
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from zoro.config.settings import ZoroSettings
from zoro.ui.app import ZoroDesktopApp, IpcWorkerThread
from zoro.ui.window import ZoroMainWindow


@pytest.fixture(scope="session")
def qapp():
    """Ensure a single QApplication instance exists for tests (headless)."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_main_window_init_and_telemetry(qapp, test_settings):
    """Verify HUD window constructs properly and updates on telemetry data."""
    win = ZoroMainWindow(settings=test_settings)
    assert "PROJECT ZORO" in win.windowTitle()
    assert win.status_pill.text() == "INITIALIZING"

    # Send mock telemetry
    data = {
        "cpu_percent": 35.5,
        "cpu_logical_cores": 8,
        "ram_used_mb": 4096.0,
        "ram_total_mb": 16384.0,
        "ram_percent": 25,
        "vram_used_mb": 1024.0,
        "vram_total_mb": 4096.0,
        "gpu_temp_c": 50.0,
        "gpu_name": "NVIDIA GeForce GTX 1050 Ti",
    }
    win.update_telemetry(data)

    assert win.cpu_bar.value() == 35
    assert "35.5 % (8 Cores)" in win.cpu_label.text()
    assert win.ram_bar.value() == 25
    assert "4.0 / 16.0 GB" in win.ram_label.text()
    assert win.vram_bar.value() == 25
    assert "1.00 / 4.0 GB (50 °C)" in win.gpu_label.text()
    assert "GTX 1050 Ti" in win.gpu_title_label.text()
    assert "RUNNING" in win.status_pill.text()

    # Append log line
    win.append_log("System operational.")
    assert "System operational." in win.console.toPlainText()


def test_main_window_close_event_minimizes(qapp, test_settings):
    """Verify close event ignores termination and hides window to tray."""
    win = ZoroMainWindow(settings=test_settings)
    win.show()
    assert win.isVisible()

    event = QCloseEvent()
    win.closeEvent(event)

    assert not win.isVisible()
    assert not event.isAccepted()  # Event was ignored, keeping app alive


def test_desktop_app_bootstrap_and_toggle(qapp, test_settings):
    """Verify ZoroDesktopApp boots, configures tray, and toggles HUD visibility."""
    app = ZoroDesktopApp(settings=test_settings)
    assert app.tray_icon is not None
    assert app.app.quitOnLastWindowClosed() is False

    # Window initially hidden or shown based on start_minimized
    app.window.hide()
    assert not app.window.isVisible()

    app._toggle_window()
    assert app.window.isVisible()

    app._toggle_window()
    assert not app.window.isVisible()

    # Clean up worker thread
    app.ipc_worker.stop()


def test_main_window_intelligence_controls(qapp, test_settings):
    """Verify Milestone 02 UI controls for AI state, approvals, benchmark, and dispatch."""
    handled_calls = []

    def mock_ipc_handler(method, params):
        handled_calls.append((method, params))
        if method == "ai.run_benchmark":
            return {"result": {"ttft_ms": 25.0, "tokens_per_sec": 45.0, "structured_json_score": 1.0, "vram_used_mb": 500.0}}
        if method == "ai.prompt":
            return {"message": "Plan executed successfully."}
        if method == "ai.resolve_approval":
            return {"message": "Approval confirmed."}
        return {}

    win = ZoroMainWindow(settings=test_settings, ipc_call_handler=mock_ipc_handler)
    win.show()

    # 1. Test update_ai_state
    win.update_ai_state({"new_state": "WAITING_FOR_APPROVAL"})
    assert "WAITING_FOR_APPROVAL" in win.ai_state_pill.text()

    win.update_ai_state({"new_state": "PLANNING"})
    assert "PLANNING" in win.ai_state_pill.text()

    win.update_ai_state({"new_state": "IDLE"})
    assert "IDLE" in win.ai_state_pill.text()

    # 2. Test step progress
    win.update_step_progress({"description": "Scan files", "status": "COMPLETED", "tool_name": "file_discovery"})
    assert "Scan files" in win.console.toPlainText()

    # 3. Test approval request and button click
    win.display_approval_request({"token": "tok-test-12345", "tool_name": "file_delete", "description": "Delete old report"})
    assert win.approval_group.isVisible()
    assert "file_delete" in win.lbl_approval_desc.text()

    win.btn_approve.click()
    assert not win.approval_group.isVisible()
    assert any(c[0] == "ai.resolve_approval" and c[1].get("approved") is True for c in handled_calls)

    # Display again and test reject
    win.display_approval_request({"token": "tok-test-67890", "tool_name": "file_delete", "description": "Delete data"})
    win.btn_reject.click()
    assert any(c[0] == "ai.resolve_approval" and c[1].get("approved") is False for c in handled_calls)

    # 4. Test provider change
    win.combo_provider.setCurrentText("ollama")
    assert any(c[0] == "ai.select_provider" for c in handled_calls)

    # 5. Test benchmark button
    win.btn_benchmark.click()
    assert any(c[0] == "ai.run_benchmark" for c in handled_calls)
    assert "Benchmark Result" in win.console.toPlainText()

    # 6. Test directive dispatch
    win.input_prompt.setText("Generate workspace report")
    win.btn_dispatch.click()
    assert any(c[0] == "ai.prompt" for c in handled_calls)
    assert "Plan executed successfully." in win.console.toPlainText()

    # 7. Test cancel button
    win.btn_cancel.click()
    assert any(c[0] == "ai.cancel" for c in handled_calls)

