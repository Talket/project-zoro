"""PySide6 Application Bootstrap, System Tray Management, and IPC Bridge."""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any, Dict, Optional
from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from zoro.config.settings import ZoroSettings, get_settings
from zoro.ipc.pipe_client import NamedPipeClient
from zoro.ui.theme import HUD_STYLESHEET
from zoro.ui.window import ZoroMainWindow

logger = logging.getLogger(__name__)


class IpcWorkerThread(threading.Thread):
    """Background worker managing the Named Pipe client connection and telemetry streaming."""

    def __init__(self, window: ZoroMainWindow, settings: ZoroSettings) -> None:
        super().__init__(name="zoro-ui-ipc-worker", daemon=True)
        self.window = window
        self.settings = settings
        self.client = NamedPipeClient(pipe_name=settings.pipe_name, settings=settings)
        self._is_running = True
        self._stop_event = threading.Event()

    def run(self) -> None:
        logger.info("UI IPC worker thread started.")
        self.window.ipc_call_handler = self.client.send_request
        self.client.register_notification_handler("telemetry.update", self._on_telemetry)
        self.client.register_notification_handler("ai.state_changed", self._on_ai_state)
        self.client.register_notification_handler("ai.approval_requested", self._on_approval_requested)
        self.client.register_notification_handler("ai.step_update", self._on_step_update)
        self.client.register_notification_handler("voice.state_changed", self._on_voice_state)
        self.client.register_notification_handler("voice.transcription", self._on_voice_transcription)
        self.client.register_notification_handler("voice.interrupted", self._on_voice_interrupted)

        backoff = 1.0
        while self._is_running:
            if not self.client.is_connected():
                connected = self.client.connect()
                if connected:
                    logger.info("UI successfully connected to ZORO Engine Named Pipe.")
                    self.window.log_message_received.emit("Connected to Core Runtime Engine via Named Pipe.")
                    backoff = 1.0
                    try:
                        health = self.client.send_request("system.get_health")
                        if health:
                            self.window.telemetry_received.emit(health)
                        providers = self.client.send_request("ai.get_providers")
                        if providers:
                            self.window.providers_received.emit(providers)
                        voice_status = self.client.send_request("voice.get_status")
                        if voice_status:
                            self.window.voice_state_received.emit(voice_status)
                    except Exception as e:
                        logger.error("Initial health request failed: %s", e)
                else:
                    self._stop_event.wait(timeout=backoff)
                    backoff = min(backoff * 1.5, self.settings.ipc_reconnect_max_backoff_sec)
            else:
                self._stop_event.wait(timeout=1.0)

    def _on_telemetry(self, method: str, data: Dict[str, Any]) -> None:
        """Forward telemetry data to Qt GUI thread via signal."""
        self.window.telemetry_received.emit(data)

    def _on_ai_state(self, method: str, data: Dict[str, Any]) -> None:
        """Forward AI orchestrator state changes to Qt GUI thread."""
        self.window.ai_state_received.emit(data)

    def _on_approval_requested(self, method: str, data: Dict[str, Any]) -> None:
        """Forward human-in-the-loop authorization request to Qt GUI thread."""
        self.window.approval_requested.emit(data)

    def _on_step_update(self, method: str, data: Dict[str, Any]) -> None:
        """Forward plan step progress to Qt GUI thread."""
        self.window.step_update_received.emit(data)

    def _on_voice_state(self, method: str, data: Dict[str, Any]) -> None:
        """Forward voice pipeline state changes to Qt GUI thread."""
        self.window.voice_state_received.emit(data)

    def _on_voice_transcription(self, method: str, data: Dict[str, Any]) -> None:
        """Forward live voice transcription to Qt GUI thread."""
        self.window.voice_transcription_received.emit(data)

    def _on_voice_interrupted(self, method: str, data: Dict[str, Any]) -> None:
        """Forward barge-in notification to Qt GUI thread."""
        self.window.log_message_received.emit("[Voice] Speech playback interrupted (barge-in).")

    def stop(self) -> None:
        self._is_running = False
        self._stop_event.set()
        self.client.close()


class ZoroDesktopApp:
    """Encapsulates the PySide6 Application, System Tray, and Main HUD."""

    def __init__(self, settings: Optional[ZoroSettings] = None) -> None:
        self.settings = settings or get_settings()
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setStyleSheet(HUD_STYLESHEET)

        self.window = ZoroMainWindow(settings=self.settings)
        self.ipc_worker = IpcWorkerThread(self.window, self.settings)

        self._setup_system_tray()

    def _setup_system_tray(self) -> None:
        """Create and configure Windows System Tray icon."""
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor(10, 15, 20))
        painter.setPen(QPen(QColor(0, 240, 255), 2))
        painter.drawEllipse(2, 2, 28, 28)
        painter.setBrush(QColor(0, 240, 255))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(12, 12, 8, 8)
        painter.end()

        self.tray_icon = QSystemTrayIcon(QIcon(pixmap), self.app)

        # Context Menu
        menu = QMenu()
        action_show = QAction("Show HUD", menu)
        action_show.triggered.connect(self._toggle_window)
        menu.addAction(action_show)

        action_emergency = QAction("EMERGENCY HARD KILL", menu)
        action_emergency.triggered.connect(self.window._on_emergency_clicked)
        menu.addAction(action_emergency)

        menu.addSeparator()

        action_exit = QAction("Exit", menu)
        action_exit.triggered.connect(self.exit_app)
        menu.addAction(action_exit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _toggle_window(self) -> None:
        """Show or hide the main HUD window."""
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.show()
            self.window.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Handle single-click or double-click on system tray."""
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._toggle_window()

    def run(self) -> int:
        """Start the IPC worker and Qt event loop."""
        self.ipc_worker.start()

        if self.settings.ui_start_minimized:
            logger.info("ZORO UI started minimized to Windows System Tray.")
            self.tray_icon.showMessage(
                "PROJECT ZORO",
                "ZORO is running in the background. Click tray icon to open HUD.",
                QSystemTrayIcon.Information,
                3000,
            )
        else:
            self.window.show()

        ret = self.app.exec()
        self.ipc_worker.stop()
        return ret

    def exit_app(self) -> None:
        """Cleanly exit UI application."""
        self.ipc_worker.stop()
        self.app.quit()
