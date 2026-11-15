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
