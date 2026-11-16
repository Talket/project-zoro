"""Tests for PySide6 Desktop HUD, System Tray, and UI Application."""

import os
import threading
import time
from unittest.mock import MagicMock, patch
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

    # 8. Test Computer Control UI widgets (Milestone 03)
    win.combo_profile.setCurrentText("PROFILE_C_RESTRICTED_MODIFICATION")
    assert any(c[0] == "computer.set_profile" for c in handled_calls)

    win.btn_capture.click()
    assert any(c[0] == "computer.capture_screen" for c in handled_calls)

    win.btn_ocr.click()
    assert any(c[0] == "computer.ocr_screen" for c in handled_calls)

    win.btn_windows.click()
    assert any(c[0] == "computer.list_windows" for c in handled_calls)

    # 9. Test Voice Interaction UI widgets (Milestone 04)
    win.update_voice_state({"new_state": "LISTENING"})
    assert "LISTENING" in win.voice_state_pill.text()

    win.update_voice_state({"new_state": "SPEAKING"})
    assert "SPEAKING" in win.voice_state_pill.text()

    win.update_voice_state({"new_state": "ERROR"})
    assert "ERROR" in win.voice_state_pill.text()

    win.update_voice_transcription({"text": "Hello Zoro", "speaker": "user"})
    assert "Hello Zoro" in win.console.toPlainText()

    win.btn_voice_toggle.click()
    assert any(c[0] == "voice.start" for c in handled_calls)

    win.btn_ptt.click()
    assert any(c[0] == "voice.push_to_talk" for c in handled_calls)

    win.btn_stop_speaking.click()
    assert any(c[0] == "voice.stop_speaking" for c in handled_calls)

    win.chk_wake_listening.setChecked(False)
    assert any(c[0] == "voice.set_wake_listening" and c[1].get("enabled") is False for c in handled_calls)

    win.chk_wake_zoro.setChecked(False)
    assert any(c[0] == "voice.configure_wake_phrase" and c[1].get("phrase") == "zoro" and c[1].get("enabled") is False for c in handled_calls)

    win.chk_wake_hey_zoro.setChecked(False)
    assert any(c[0] == "voice.configure_wake_phrase" and c[1].get("phrase") == "hey zoro" and c[1].get("enabled") is False for c in handled_calls)


def test_ui_ipc_worker_notifications_and_tray(qapp, test_settings):
    """Verify IpcWorkerThread notification forwarding and system tray interactions."""
    app = ZoroDesktopApp(settings=test_settings)
    worker = app.ipc_worker

    # Notification handlers forwarding to signals
    worker._on_telemetry("telemetry.update", {"cpu_percent": 10})
    worker._on_ai_state("ai.state_changed", {"new_state": "IDLE"})
    worker._on_approval_requested("ai.approval_requested", {"token": "test-token"})
    worker._on_step_update("ai.step_update", {"description": "Running tool"})
    worker._on_voice_state("voice.state_changed", {"new_state": "LISTENING"})
    worker._on_voice_transcription("voice.transcription", {"text": "What time is it?"})
    worker._on_voice_interrupted("voice.interrupted", {})

    # Tray activation
    from PySide6.QtWidgets import QSystemTrayIcon
    app._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert app.window.isVisible()
    app._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
    assert not app.window.isVisible()

    app._toggle_window()
    assert app.window.isVisible()

    worker.stop()


def test_ui_ipc_worker_run_and_exit_app(qapp, test_settings):
    """Verify IpcWorkerThread run loop connection and app exit."""
    app = ZoroDesktopApp(settings=test_settings)
    worker = app.ipc_worker

    # Mock client connection loop
    with patch.object(worker.client, "is_connected", side_effect=[False, True]), \
         patch.object(worker.client, "connect", return_value=True), \
         patch.object(worker.client, "send_request", return_value={"ok": True}):
        
        def stop_soon():
            time.sleep(0.05)
            worker.stop()
        
        t = threading.Thread(target=stop_soon)
        t.start()
        worker.run()
        t.join()

    # Test exit_app
    with patch.object(app.app, "quit"):
        app.exit_app()


