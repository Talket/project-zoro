"""Main HUD Desktop Window displaying real-time telemetry and controls."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from zoro.config.settings import ZoroSettings, get_settings
from zoro.security.emergency import EmergencyManager


class ZoroMainWindow(QMainWindow):
    """JARVIS-inspired modern HUD window for PROJECT ZORO."""

    # Qt Signals for thread-safe UI updates from IPC client
    telemetry_received = Signal(dict)
    log_message_received = Signal(str)

    def __init__(self, settings: Optional[ZoroSettings] = None) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        self.emergency_mgr = EmergencyManager()

        self.setWindowTitle("PROJECT ZORO // SYSTEM HUD")
        self.resize(self.settings.ui_window_width, self.settings.ui_window_height)

        self._build_ui()
        self.telemetry_received.connect(self.update_telemetry)
        self.log_message_received.connect(self.append_log)

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # 1. Header Bar
        header_layout = QHBoxLayout()
        title_label = QLabel("PROJECT ZORO  //  PERSISTENT INTELLIGENCE", self)
        title_label.setObjectName("titleLabel")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self.status_pill = QLabel("INITIALIZING", self)
        self.status_pill.setObjectName("statusPill")
        header_layout.addWidget(self.status_pill)

        main_layout.addLayout(header_layout)

        # 2. Hardware Telemetry Section
        telemetry_group = QGroupBox("HOST HARDWARE TELEMETRY", self)
        telemetry_layout = QVBoxLayout(telemetry_group)
        telemetry_layout.setSpacing(12)

        # CPU Row
        cpu_box = QHBoxLayout()
        cpu_box.addWidget(QLabel("CPU LOAD:", self))
        self.cpu_bar = QProgressBar(self)
        self.cpu_bar.setRange(0, 100)
        self.cpu_bar.setValue(0)
        cpu_box.addWidget(self.cpu_bar)
        self.cpu_label = QLabel("0.0 % (8 Logical Cores)", self)
        self.cpu_label.setFixedWidth(180)
        cpu_box.addWidget(self.cpu_label)
        telemetry_layout.addLayout(cpu_box)

        # RAM Row
        ram_box = QHBoxLayout()
        ram_box.addWidget(QLabel("SYSTEM RAM:", self))
        self.ram_bar = QProgressBar(self)
        self.ram_bar.setRange(0, 100)
        self.ram_bar.setValue(0)
        ram_box.addWidget(self.ram_bar)
        self.ram_label = QLabel("0.0 / 16.0 GB", self)
        self.ram_label.setFixedWidth(180)
        ram_box.addWidget(self.ram_label)
        telemetry_layout.addLayout(ram_box)

        # GPU & VRAM Row
        gpu_box = QHBoxLayout()
        self.gpu_title_label = QLabel("GPU / VRAM:", self)
        gpu_box.addWidget(self.gpu_title_label)
        self.vram_bar = QProgressBar(self)
        self.vram_bar.setRange(0, 100)
        self.vram_bar.setValue(0)
        gpu_box.addWidget(self.vram_bar)
        self.gpu_label = QLabel("0.0 / 4.0 GB (0 °C)", self)
        self.gpu_label.setFixedWidth(180)
        gpu_box.addWidget(self.gpu_label)
        telemetry_layout.addLayout(gpu_box)

        main_layout.addWidget(telemetry_group)

        # 3. Activity Feed / HUD Console
        feed_group = QGroupBox("ACTIVITY & SECURITY AUDIT FEED", self)
        feed_layout = QVBoxLayout(feed_group)
        self.console = QTextEdit(self)
        self.console.setReadOnly(True)
        feed_layout.addWidget(self.console)
        main_layout.addWidget(feed_group)

        # 4. Action Controls Bar
        action_layout = QHBoxLayout()

        self.btn_clear_log = QPushButton("Clear Display", self)
        self.btn_clear_log.clicked.connect(self.console.clear)
        action_layout.addWidget(self.btn_clear_log)

        action_layout.addStretch()

        self.btn_emergency = QPushButton("EMERGENCY HARD KILL", self)
        self.btn_emergency.setObjectName("emergencyButton")
        self.btn_emergency.clicked.connect(self._on_emergency_clicked)
        action_layout.addWidget(self.btn_emergency)

        main_layout.addLayout(action_layout)

    @Slot(dict)
    def update_telemetry(self, data: Dict[str, Any]) -> None:
        """Update live telemetry progress bars and labels."""
        # CPU
        cpu_pct = int(data.get("cpu_percent", 0))
        self.cpu_bar.setValue(cpu_pct)
        cores = data.get("cpu_logical_cores", 8)
        self.cpu_label.setText(f"{data.get('cpu_percent', 0.0):.1f} % ({cores} Cores)")

        # RAM
        ram_used = data.get("ram_used_mb", 0.0) / 1024
        ram_total = data.get("ram_total_mb", 16384.0) / 1024
        ram_pct = int(data.get("ram_percent", 0))
        self.ram_bar.setValue(ram_pct)
        self.ram_label.setText(f"{ram_used:.1f} / {ram_total:.1f} GB")

        # GPU
        vram_used = data.get("vram_used_mb")
        vram_total = data.get("vram_total_mb")
        gpu_temp = data.get("gpu_temp_c", 0)
        gpu_name = data.get("gpu_name", "GPU")

        if vram_used is not None and vram_total is not None and vram_total > 0:
            vram_pct = int((vram_used / vram_total) * 100)
            self.vram_bar.setValue(vram_pct)
            self.gpu_label.setText(f"{vram_used / 1024:.2f} / {vram_total / 1024:.1f} GB ({gpu_temp:.0f} °C)")
            self.gpu_title_label.setText(f"{gpu_name}:")

        self.status_pill.setText("RUNNING // HEALTHY")

    @Slot(str)
    def append_log(self, text: str) -> None:
        """Append log line to HUD console."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console.append(f"[{timestamp}] {text}")

    def _on_emergency_clicked(self) -> None:
        """Trigger emergency hard kill."""
        self.append_log("[CRITICAL] EMERGENCY KILL BUTTON PRESSED BY USER.")
        self.status_pill.setText("HALTED // KILL ACTIVATED")
        self.emergency_mgr.trigger_emergency_kill("Emergency button in Desktop HUD pressed.")

    def closeEvent(self, event) -> None:
        """Minimize to tray instead of quitting when window close button is pressed."""
        event.ignore()
        self.hide()
