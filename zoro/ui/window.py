"""Main HUD Desktop Window displaying real-time telemetry, AI runtime controls, and task planning."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    ai_state_received = Signal(dict)
    approval_requested = Signal(dict)
    step_update_received = Signal(dict)
    providers_received = Signal(dict)
    benchmarks_received = Signal(dict)
    voice_state_received = Signal(dict)
    voice_transcription_received = Signal(dict)

    def __init__(
        self,
        settings: Optional[ZoroSettings] = None,
        ipc_call_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> None:
        super().__init__()
        self.settings = settings or get_settings()
        self.emergency_mgr = EmergencyManager()

        # IPC dispatch callback set by app.py
        self.ipc_call_handler = ipc_call_handler
        self._current_approval_token: Optional[str] = None

        self.setWindowTitle("PROJECT ZORO // SYSTEM HUD")
        self.resize(self.settings.ui_window_width, self.settings.ui_window_height + 150)

        self._build_ui()
        self.telemetry_received.connect(self.update_telemetry)
        self.log_message_received.connect(self.append_log)
        self.ai_state_received.connect(self.update_ai_state)
        self.approval_requested.connect(self.display_approval_request)
        self.step_update_received.connect(self.update_step_progress)
        self.providers_received.connect(self.update_providers)
        self.voice_state_received.connect(self.update_voice_state)
        self.voice_transcription_received.connect(self.update_voice_transcription)

    def _build_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(14)

        # 1. Header Bar
        header_layout = QHBoxLayout()
        title_label = QLabel("PROJECT ZORO  //  PERSISTENT INTELLIGENCE", self)
        title_label.setObjectName("titleLabel")
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self.status_pill = QLabel("INITIALIZING", self)
        self.status_pill.setObjectName("statusPill")
        header_layout.addWidget(self.status_pill)

        self.ai_state_pill = QLabel("AI: IDLE", self)
        self.ai_state_pill.setObjectName("aiStatePill")
        self.ai_state_pill.setStyleSheet("background-color: #1a2332; color: #00f0ff; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        header_layout.addWidget(self.ai_state_pill)

        main_layout.addLayout(header_layout)

        # 2. Hardware Telemetry Section
        telemetry_group = QGroupBox("HOST HARDWARE TELEMETRY", self)
        telemetry_layout = QVBoxLayout(telemetry_group)
        telemetry_layout.setSpacing(8)

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
        cpu_box.addWidget(self.ram_label)
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

        # 3. AI Runtime & Provider Section (Milestone 02)
        ai_runtime_group = QGroupBox("INTELLIGENCE CORE & LOCAL RUNTIME", self)
        ai_layout = QHBoxLayout(ai_runtime_group)
        ai_layout.setSpacing(12)

        ai_layout.addWidget(QLabel("PROVIDER:", self))
        self.combo_provider = QComboBox(self)
        self.combo_provider.addItems(["mock", "ollama", "llama.cpp"])
        self.combo_provider.currentTextChanged.connect(self._on_provider_changed)
        ai_layout.addWidget(self.combo_provider)

        ai_layout.addWidget(QLabel("MODEL:", self))
        self.combo_model = QComboBox(self)
        self.combo_model.addItems(["mock-v1", "qwen2.5:3b", "default"])
        ai_layout.addWidget(self.combo_model)

        self.btn_benchmark = QPushButton("Benchmark Model", self)
        self.btn_benchmark.clicked.connect(self._on_benchmark_clicked)
        ai_layout.addWidget(self.btn_benchmark)

        main_layout.addWidget(ai_runtime_group)

        # 4. Interactive Directive Input Bar
        directive_group = QGroupBox("USER DIRECTIVE & PROMPT DISPATCH", self)
        directive_layout = QHBoxLayout(directive_group)
        self.input_prompt = QLineEdit(self)
        self.input_prompt.setPlaceholderText("Enter command or request, e.g. 'Find all PDF files in Downloads and generate report'...")
        self.input_prompt.returnPressed.connect(self._on_dispatch_clicked)
        directive_layout.addWidget(self.input_prompt)

        self.btn_dispatch = QPushButton("DISPATCH DIRECTIVE", self)
        self.btn_dispatch.setStyleSheet("background-color: #008899; color: #ffffff; font-weight: bold;")
        self.btn_dispatch.clicked.connect(self._on_dispatch_clicked)
        directive_layout.addWidget(self.btn_dispatch)

        self.btn_cancel = QPushButton("CANCEL", self)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        directive_layout.addWidget(self.btn_cancel)

        main_layout.addWidget(directive_group)

        # 4b. Computer Control & Desktop Automation Panel (Milestone 03)
        computer_group = QGroupBox("COMPUTER CONTROL & EXECUTION SANDBOX", self)
        comp_layout = QHBoxLayout(computer_group)
        comp_layout.setSpacing(10)

        comp_layout.addWidget(QLabel("SANDBOX PROFILE:", self))
        self.combo_profile = QComboBox(self)
        self.combo_profile.addItems([
            "PROFILE_B_STANDARD",
            "PROFILE_A_READ_ONLY",
            "PROFILE_C_RESTRICTED_MODIFICATION",
            "PROFILE_D_HIGH_RISK",
        ])
        self.combo_profile.currentTextChanged.connect(self._on_profile_changed)
        comp_layout.addWidget(self.combo_profile)

        self.btn_capture = QPushButton("Capture Screen", self)
        self.btn_capture.clicked.connect(self._on_capture_screen_clicked)
        comp_layout.addWidget(self.btn_capture)

        self.btn_ocr = QPushButton("Screen OCR", self)
        self.btn_ocr.clicked.connect(self._on_screen_ocr_clicked)
        comp_layout.addWidget(self.btn_ocr)

        self.btn_windows = QPushButton("List Windows", self)
        self.btn_windows.clicked.connect(self._on_list_windows_clicked)
        comp_layout.addWidget(self.btn_windows)

        main_layout.addWidget(computer_group)

        # 4b. Voice Control & Audio Interaction (Milestone 04)
        voice_group = QGroupBox("VOICE INTERACTION & AUDIO PIPELINE", self)
        voice_layout = QVBoxLayout(voice_group)

        voice_top_row = QHBoxLayout()
        self.btn_voice_toggle = QPushButton("Enable Voice", self)
        self.btn_voice_toggle.clicked.connect(self._on_voice_toggle_clicked)
        voice_top_row.addWidget(self.btn_voice_toggle)

        self.btn_ptt = QPushButton("Push-to-Talk", self)
        self.btn_ptt.setStyleSheet("background-color: #1a3344; font-weight: bold;")
        self.btn_ptt.clicked.connect(self._on_ptt_clicked)
        voice_top_row.addWidget(self.btn_ptt)

        self.btn_stop_speaking = QPushButton("Stop Speaking", self)
        self.btn_stop_speaking.setStyleSheet("background-color: #552222;")
        self.btn_stop_speaking.clicked.connect(self._on_stop_speaking_clicked)
        voice_top_row.addWidget(self.btn_stop_speaking)

        self.voice_state_pill = QLabel("VOICE: DISABLED", self)
        self.voice_state_pill.setStyleSheet("background-color: #1a2332; color: #00f0ff; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        voice_top_row.addWidget(self.voice_state_pill)

        voice_layout.addLayout(voice_top_row)

        voice_opts_row = QHBoxLayout()
        self.chk_wake_listening = QCheckBox("Wake-Word Listening", self)
        self.chk_wake_listening.setChecked(True)
        self.chk_wake_listening.toggled.connect(self._on_wake_listening_toggled)
        voice_opts_row.addWidget(self.chk_wake_listening)

        self.chk_wake_zoro = QCheckBox("Wake: 'Zoro'", self)
        self.chk_wake_zoro.setChecked(True)
        self.chk_wake_zoro.toggled.connect(lambda chk: self._on_wake_phrase_toggled("zoro", chk))
        voice_opts_row.addWidget(self.chk_wake_zoro)

        self.chk_wake_hey_zoro = QCheckBox("Wake: 'Hey Zoro'", self)
        self.chk_wake_hey_zoro.setChecked(True)
        self.chk_wake_hey_zoro.toggled.connect(lambda chk: self._on_wake_phrase_toggled("hey zoro", chk))
        voice_opts_row.addWidget(self.chk_wake_hey_zoro)

        voice_layout.addLayout(voice_opts_row)
        main_layout.addWidget(voice_group)

        # 5. Interactive Human-in-the-Loop Approval Box (Hidden until needed)
        self.approval_group = QGroupBox("SECURITY AUTHORIZATION REQUIRED", self)
        self.approval_group.setStyleSheet("QGroupBox { border: 2px solid #ffaa00; background-color: #1e1910; }")
        approval_layout = QVBoxLayout(self.approval_group)
        self.lbl_approval_desc = QLabel("Action requires authorization.", self)
        self.lbl_approval_desc.setStyleSheet("color: #ffcc00; font-weight: bold;")
        approval_layout.addWidget(self.lbl_approval_desc)

        approval_btn_box = QHBoxLayout()
        self.btn_approve = QPushButton("AUTHORIZE OPERATION", self)
        self.btn_approve.setStyleSheet("background-color: #228833; color: white; font-weight: bold;")
        self.btn_approve.clicked.connect(lambda: self._on_resolve_approval(True))
        approval_btn_box.addWidget(self.btn_approve)

        self.btn_reject = QPushButton("REJECT OPERATION", self)
        self.btn_reject.setStyleSheet("background-color: #aa2222; color: white; font-weight: bold;")
        self.btn_reject.clicked.connect(lambda: self._on_resolve_approval(False))
        approval_btn_box.addWidget(self.btn_reject)

        approval_layout.addLayout(approval_btn_box)
        self.approval_group.hide()
        main_layout.addWidget(self.approval_group)

        # 6. Activity & Security Audit Feed Console
        feed_group = QGroupBox("ACTIVITY & SECURITY AUDIT FEED", self)
        feed_layout = QVBoxLayout(feed_group)
        self.console = QTextEdit(self)
        self.console.setReadOnly(True)
        feed_layout.addWidget(self.console)
        main_layout.addWidget(feed_group)

        # 7. Bottom Action Controls Bar
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
        cpu_pct = int(data.get("cpu_percent", 0))
        self.cpu_bar.setValue(cpu_pct)
        cores = data.get("cpu_logical_cores", 8)
        self.cpu_label.setText(f"{data.get('cpu_percent', 0.0):.1f} % ({cores} Cores)")

        ram_used = data.get("ram_used_mb", 0.0) / 1024
        ram_total = data.get("ram_total_mb", 16384.0) / 1024
        ram_pct = int(data.get("ram_percent", 0))
        self.ram_bar.setValue(ram_pct)
        self.ram_label.setText(f"{ram_used:.1f} / {ram_total:.1f} GB")

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

    @Slot(dict)
    def update_ai_state(self, payload: Dict[str, Any]) -> None:
        new_state = payload.get("new_state", "IDLE")
        self.ai_state_pill.setText(f"AI: {new_state}")
        if new_state in ("WAITING_FOR_APPROVAL", "FAILED"):
            self.ai_state_pill.setStyleSheet("background-color: #3d2010; color: #ffaa00; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        elif new_state in ("EXECUTING", "PLANNING", "UNDERSTANDING"):
            self.ai_state_pill.setStyleSheet("background-color: #102a3d; color: #00f0ff; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        else:
            self.ai_state_pill.setStyleSheet("background-color: #1a2332; color: #00f0ff; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.append_log(f"[AI State] Transitioned to {new_state}")

    @Slot(dict)
    def display_approval_request(self, payload: Dict[str, Any]) -> None:
        self._current_approval_token = payload.get("token")
        desc = payload.get("description", "A sensitive operation requires user approval.")
        tool = payload.get("tool_name", "Tool")
        self.lbl_approval_desc.setText(f"ACTION REQUIRED: [{tool}] {desc}")
        self.approval_group.show()
        self.append_log(f"[APPROVAL] Authorization requested for {tool}: {desc}")

    @Slot(dict)
    def update_step_progress(self, payload: Dict[str, Any]) -> None:
        desc = payload.get("description", "")
        status = payload.get("status", "")
        tool = payload.get("tool_name", "")
        self.append_log(f"[Plan Step] '{desc}' via [{tool}] -> {status}")

    @Slot(dict)
    def update_providers(self, data: Dict[str, Any]) -> None:
        active = data.get("active_provider")
        if active and active in ["mock", "ollama", "llama.cpp"]:
            self.combo_provider.setCurrentText(active)

    @Slot(str)
    def append_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console.append(f"[{timestamp}] {text}")

    def _on_provider_changed(self, provider_name: str) -> None:
        self.append_log(f"Selected AI Provider: {provider_name}")
        if self.ipc_call_handler:
            self.ipc_call_handler("ai.select_provider", {"provider": provider_name})

    def _on_benchmark_clicked(self) -> None:
        provider = self.combo_provider.currentText()
        model = self.combo_model.currentText()
        self.append_log(f"Initiating benchmark on {provider}/{model}...")
        if self.ipc_call_handler:
            res = self.ipc_call_handler("ai.run_benchmark", {"provider": provider, "model": model})
            if res and "result" in res:
                m = res["result"]
                self.append_log(f"[Benchmark Result] TTFT: {m.get('ttft_ms')}ms | Tok/s: {m.get('tokens_per_sec')} | JSON Score: {m.get('structured_json_score')} | VRAM: {m.get('vram_used_mb')}MB")

    def _on_dispatch_clicked(self) -> None:
        prompt = self.input_prompt.text().strip()
        if not prompt:
            return
        self.input_prompt.clear()
        self.append_log(f">> USER DIRECTIVE: {prompt}")
        if self.ipc_call_handler:
            res = self.ipc_call_handler("ai.prompt", {"prompt": prompt})
            if res and "message" in res:
                self.append_log(f"<< ZORO: {res['message']}")

    def _on_cancel_clicked(self) -> None:
        self.append_log("[COMMAND] Cancelling active operation...")
        if self.ipc_call_handler:
            self.ipc_call_handler("ai.cancel", {})

    def _on_resolve_approval(self, approved: bool) -> None:
        self.approval_group.hide()
        if not self._current_approval_token:
            return
        token = self._current_approval_token
        self._current_approval_token = None
        action_str = "APPROVED" if approved else "REJECTED"
        self.append_log(f"[Decision] User {action_str} operation token {token[:8]}.")
        if self.ipc_call_handler:
            res = self.ipc_call_handler("ai.resolve_approval", {"token": token, "approved": approved})
            if res and "message" in res:
                self.append_log(f"<< ZORO: {res['message']}")

    def _on_emergency_clicked(self) -> None:
        self.append_log("[CRITICAL] EMERGENCY KILL BUTTON PRESSED BY USER.")
        self.status_pill.setText("HALTED // KILL ACTIVATED")
        self.emergency_mgr.trigger_emergency_kill("Emergency button in Desktop HUD pressed.")

    def _on_profile_changed(self, profile_name: str) -> None:
        self.append_log(f"[Sandbox] Switching profile to {profile_name}...")
        if self.ipc_call_handler:
            res = self.ipc_call_handler("computer.set_profile", {"profile": profile_name})
            if res and res.get("success"):
                self.append_log(f"[Sandbox] Active profile set to {res.get('profile')}")

    def _on_capture_screen_clicked(self) -> None:
        self.append_log("[Perception] Requesting desktop screen capture...")
        if self.ipc_call_handler:
            res = self.ipc_call_handler("computer.capture_screen", {})
            if res and res.get("success"):
                self.append_log(f"[Screen Capture] Saved: {res.get('image_path')} ({res.get('width')}x{res.get('height')})")
            elif res:
                self.append_log(f"[Screen Capture Error] {res.get('error')}")

    def _on_screen_ocr_clicked(self) -> None:
        self.append_log("[Perception] Running WinRT Screen OCR...")
        if self.ipc_call_handler:
            res = self.ipc_call_handler("computer.ocr_screen", {})
            if res and res.get("success"):
                txt = (res.get("text") or "").strip()
                preview = txt[:200] + ("..." if len(txt) > 200 else "")
                self.append_log(f"[OCR Result] Extracted text ({len(res.get('words', []))} words):\n{preview}")
            elif res:
                self.append_log(f"[OCR Error] {res.get('error')}")

    def _on_list_windows_clicked(self) -> None:
        self.append_log("[UI Automation] Querying active desktop windows...")
        if self.ipc_call_handler:
            res = self.ipc_call_handler("computer.list_windows", {"visible_only": True})
            if res and "windows" in res:
                wins = res["windows"][:5]
                summary = ", ".join([f"'{w.get('title')}' ({w.get('handle')})" for w in wins if w.get("title")])
                self.append_log(f"[Windows ({len(res['windows'])})] Top active: {summary}")

    @Slot(dict)
    def update_voice_state(self, payload: Dict[str, Any]) -> None:
        new_state = payload.get("new_state", payload.get("state", "IDLE"))
        self.voice_state_pill.setText(f"VOICE: {new_state}")
        if "is_enabled" in payload:
            is_en = payload["is_enabled"]
            self.btn_voice_toggle.setText("Disable Voice" if is_en else "Enable Voice")
        if new_state in ("LISTENING", "DETECTED"):
            self.voice_state_pill.setStyleSheet("background-color: #003322; color: #00ff88; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        elif new_state in ("SPEAKING", "TRANSCRIBING", "PROCESSING"):
            self.voice_state_pill.setStyleSheet("background-color: #102a3d; color: #00f0ff; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        elif new_state in ("ERROR", "MUTED"):
            self.voice_state_pill.setStyleSheet("background-color: #3d1010; color: #ff4444; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        else:
            self.voice_state_pill.setStyleSheet("background-color: #1a2332; color: #00f0ff; padding: 4px 10px; border-radius: 4px; font-weight: bold;")
        self.append_log(f"[Voice] State -> {new_state}")

    @Slot(dict)
    def update_voice_transcription(self, payload: Dict[str, Any]) -> None:
        text = payload.get("text", "")
        speaker = payload.get("speaker", "user")
        if text:
            self.append_log(f"[Voice Transcription ({speaker})] \"{text}\"")

    def _on_voice_toggle_clicked(self) -> None:
        if self.btn_voice_toggle.text() == "Enable Voice":
            self.append_log("[Voice] Enabling voice interaction...")
            if self.ipc_call_handler:
                res = self.ipc_call_handler("voice.start", {})
                if res and (res.get("started") or res.get("success")):
                    self.btn_voice_toggle.setText("Disable Voice")
                    self.append_log("[Voice] Voice interaction active.")
        else:
            self.append_log("[Voice] Disabling voice interaction...")
            if self.ipc_call_handler:
                res = self.ipc_call_handler("voice.stop", {})
                self.btn_voice_toggle.setText("Enable Voice")
                self.append_log("[Voice] Voice interaction stopped.")

    def _on_ptt_clicked(self) -> None:
        self.append_log("[Voice] Push-to-Talk triggered.")
        if self.ipc_call_handler:
            self.ipc_call_handler("voice.push_to_talk", {})

    def _on_stop_speaking_clicked(self) -> None:
        self.append_log("[Voice] User requested immediate speech stop.")
        if self.ipc_call_handler:
            self.ipc_call_handler("voice.stop_speaking", {})

    def _on_wake_listening_toggled(self, checked: bool) -> None:
        action = "enabled" if checked else "disabled"
        self.append_log(f"[Voice] Wake-word listening {action}.")
        if self.ipc_call_handler:
            self.ipc_call_handler("voice.set_wake_listening", {"enabled": checked})

    def _on_wake_phrase_toggled(self, phrase: str, checked: bool) -> None:
        status = "enabled" if checked else "disabled"
        self.append_log(f"[Voice] Wake phrase '{phrase}' {status}.")
        if self.ipc_call_handler:
            self.ipc_call_handler("voice.configure_wake_phrase", {"phrase": phrase, "enabled": checked})

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
