"""Interactive PySide6 Timetable, Deadlines, and Focus Mode Panel for PROJECT ZORO."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class ZoroTimetableDialog(QDialog):
    """JARVIS-inspired interactive Timetable, Deadlines, and Focus Mode Manager."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        ipc_call_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
    ) -> None:
        super().__init__(parent)
        self.ipc_call = ipc_call_handler
        self.setWindowTitle("PROJECT ZORO // TIMETABLE & PROACTIVE INTELLIGENCE")
        self.resize(850, 600)
        self.setMinimumSize(750, 500)

        self._build_ui()
        self._load_data()

        # Timer for live focus session countdown
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh_focus_status)
        self._timer.start(5000)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Header Title
        header_box = QHBoxLayout()
        lbl_title = QLabel("TIMETABLE & PROACTIVE INTELLIGENCE", self)
        lbl_title.setObjectName("titleLabel")
        header_box.addWidget(lbl_title)
        header_box.addStretch()

        self.btn_refresh = QPushButton("Refresh Data", self)
        self.btn_refresh.clicked.connect(self._load_data)
        header_box.addWidget(self.btn_refresh)
        layout.addLayout(header_box)

        # Tab Widget
        self.tabs = QTabWidget(self)

        # Tab 1: Today's Agenda & Deadlines
        self.tab_agenda = QWidget()
        self._build_agenda_tab(self.tab_agenda)
        self.tabs.addTab(self.tab_agenda, "Agenda & Deadlines")

        # Tab 2: Full Timetable & Events
        self.tab_events = QWidget()
        self._build_events_tab(self.tab_events)
        self.tabs.addTab(self.tab_events, "Timetable Events")

        # Tab 3: Deep Work & Focus Mode
        self.tab_focus = QWidget()
        self._build_focus_tab(self.tab_focus)
        self.tabs.addTab(self.tab_focus, "Focus Mode")

        # Tab 4: Quiet Hours & Settings
        self.tab_settings = QWidget()
        self._build_settings_tab(self.tab_settings)
        self.tabs.addTab(self.tab_settings, "Quiet Hours & Settings")

        # Tab 5: Notification History
        self.tab_history = QWidget()
        self._build_history_tab(self.tab_history)
        self.tabs.addTab(self.tab_history, "Alert History")

        layout.addWidget(self.tabs)

        # Bottom Close Button
        bottom_box = QHBoxLayout()
        bottom_box.addStretch()
        btn_close = QPushButton("Close", self)
        btn_close.clicked.connect(self.accept)
        bottom_box.addWidget(btn_close)
        layout.addLayout(bottom_box)

    # -------------------------------------------------------------------------
    # Tab 1: Agenda & Deadlines
    # -------------------------------------------------------------------------
    def _build_agenda_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setSpacing(10)

        # Briefing summary box
        grp_briefing = QGroupBox("DAILY SITUATIONAL BRIEFING", parent)
        b_layout = QVBoxLayout(grp_briefing)
        self.txt_briefing = QTextEdit(parent)
        self.txt_briefing.setReadOnly(True)
        self.txt_briefing.setPlaceholderText("Loading today's briefing...")
        b_layout.addWidget(self.txt_briefing)
        layout.addWidget(grp_briefing)

    # -------------------------------------------------------------------------
    # Tab 2: Full Timetable Events Table
    # -------------------------------------------------------------------------
    def _build_events_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setSpacing(10)

        # Filter bar
        filter_box = QHBoxLayout()
        filter_box.addWidget(QLabel("Category:", parent))
        self.combo_cat = QComboBox(parent)
        self.combo_cat.addItems(["ALL", "COLLEGE", "EXAMS", "ASSIGNMENTS", "PROJECTS", "PERSONAL", "MEETINGS", "GENERAL_TASKS"])
        self.combo_cat.currentTextChanged.connect(self._on_filter_changed)
        filter_box.addWidget(self.combo_cat)

        filter_box.addStretch()

        self.btn_new_event = QPushButton("+ Add Event", parent)
        self.btn_new_event.setStyleSheet("background-color: #008899; color: white; font-weight: bold;")
        self.btn_new_event.clicked.connect(self._on_add_event_clicked)
        filter_box.addWidget(self.btn_new_event)
        layout.addLayout(filter_box)

        # Events Table
        self.table_events = QTableWidget(parent)
        self.table_events.setColumnCount(6)
        self.table_events.setHorizontalHeaderLabels(["Title", "Category", "Priority", "Date", "Time", "Status"])
        self.table_events.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_events.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_events.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table_events)

        # Table Action Bar
        action_box = QHBoxLayout()
        self.btn_delete_event = QPushButton("Delete Selected Event", parent)
        self.btn_delete_event.setStyleSheet("background-color: #551111;")
        self.btn_delete_event.clicked.connect(self._on_delete_event_clicked)
        action_box.addWidget(self.btn_delete_event)
        action_box.addStretch()
        layout.addLayout(action_box)

    # -------------------------------------------------------------------------
    # Tab 3: Deep Work & Focus Mode
    # -------------------------------------------------------------------------
    def _build_focus_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setSpacing(14)

        grp_start = QGroupBox("ENGAGE DEEP WORK SESSION", parent)
        form = QFormLayout(grp_start)
        self.txt_focus_task = QLineEdit(parent)
        self.txt_focus_task.setPlaceholderText("Enter target focus task (e.g. 'Complete DAA graph algorithm analysis')...")
        form.addRow("Task Objective:", self.txt_focus_task)

        self.spin_focus_mins = QSpinBox(parent)
        self.spin_focus_mins.setRange(5, 480)
        self.spin_focus_mins.setValue(45)
        self.spin_focus_mins.setSuffix(" minutes")
        form.addRow("Duration:", self.spin_focus_mins)

        self.btn_start_focus = QPushButton("START FOCUS SESSION", parent)
        self.btn_start_focus.setStyleSheet("background-color: #008899; color: white; font-weight: bold; padding: 10px;")
        self.btn_start_focus.clicked.connect(self._on_start_focus_clicked)
        form.addRow("", self.btn_start_focus)
        layout.addWidget(grp_start)

        grp_status = QGroupBox("ACTIVE SESSION MONITOR", parent)
        stat_layout = QVBoxLayout(grp_status)
        self.lbl_focus_status = QLabel("No active focus session.", parent)
        self.lbl_focus_status.setStyleSheet("font-size: 14px; font-weight: bold; color: #38bdf8;")
        stat_layout.addWidget(self.lbl_focus_status)

        self.btn_stop_focus = QPushButton("Stop Session Early", parent)
        self.btn_stop_focus.setStyleSheet("background-color: #552222;")
        self.btn_stop_focus.clicked.connect(self._on_stop_focus_clicked)
        self.btn_stop_focus.setEnabled(False)
        stat_layout.addWidget(self.btn_stop_focus)
        layout.addWidget(grp_status)
        layout.addStretch()

    # -------------------------------------------------------------------------
    # Tab 4: Quiet Hours & Settings
    # -------------------------------------------------------------------------
    def _build_settings_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setSpacing(14)

        grp_qh = QGroupBox("QUIET HOURS CONFIGURATION", parent)
        form_qh = QFormLayout(grp_qh)
        self.combo_qh_enabled = QComboBox(parent)
        self.combo_qh_enabled.addItems(["Enabled", "Disabled"])
        form_qh.addRow("Quiet Hours:", self.combo_qh_enabled)

        self.txt_qh_start = QLineEdit("23:00", parent)
        form_qh.addRow("Start Time (24h):", self.txt_qh_start)

        self.txt_qh_end = QLineEdit("07:00", parent)
        form_qh.addRow("End Time (24h):", self.txt_qh_end)
        layout.addWidget(grp_qh)

        grp_brief = QGroupBox("PROACTIVE BRIEFING & TIMEZONE", parent)
        form_br = QFormLayout(grp_brief)
        self.txt_brief_time = QLineEdit("08:30", parent)
        form_br.addRow("Morning Briefing Time:", self.txt_brief_time)

        self.txt_timezone = QLineEdit("Asia/Kolkata", parent)
        self.txt_timezone.setReadOnly(True)
        form_br.addRow("System Timezone:", self.txt_timezone)
        layout.addWidget(grp_brief)

        self.btn_save_settings = QPushButton("Save Schedule Settings", parent)
        self.btn_save_settings.setStyleSheet("background-color: #008899; color: white; font-weight: bold; padding: 8px;")
        self.btn_save_settings.clicked.connect(self._on_save_settings_clicked)
        layout.addWidget(self.btn_save_settings)
        layout.addStretch()

    # -------------------------------------------------------------------------
    # Tab 5: Notification History Table
    # -------------------------------------------------------------------------
    def _build_history_tab(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setSpacing(10)

        self.table_notifs = QTableWidget(parent)
        self.table_notifs.setColumnCount(4)
        self.table_notifs.setHorizontalHeaderLabels(["Title", "Channel", "Status", "Dispatched (UTC)"])
        self.table_notifs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_notifs.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_notifs.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_notifs.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table_notifs)

        btn_box = QHBoxLayout()
        self.btn_clear_notifs = QPushButton("Clear Notification History", parent)
        self.btn_clear_notifs.clicked.connect(self._on_clear_notifs_clicked)
        btn_box.addWidget(self.btn_clear_notifs)
        btn_box.addStretch()
        layout.addLayout(btn_box)

    # -------------------------------------------------------------------------
    # Data Loading & Event Handlers
    # -------------------------------------------------------------------------
    def _load_data(self) -> None:
        if not self.ipc_call:
            return

        # 1. Load Daily Briefing
        res = self.ipc_call("schedule.get_briefing", {})
        if res:
            brief_text = res.get("summary")
            if not brief_text and isinstance(res.get("briefing"), dict):
                brief_text = res["briefing"].get("summary_text")
            if brief_text:
                self.txt_briefing.setPlainText(brief_text)

        # 2. Load Events Table
        cat = self.combo_cat.currentText()
        params = {}
        if cat != "ALL":
            params["category"] = cat
        res_ev = self.ipc_call("schedule.list_events", params)
        if res_ev and "events" in res_ev:
            self._populate_events_table(res_ev["events"])

        # 3. Load Settings
        raw_set = self.ipc_call("schedule.get_settings", {})
        if raw_set:
            res_set = raw_set.get("settings", raw_set) if isinstance(raw_set, dict) else {}
            self.combo_qh_enabled.setCurrentText("Enabled" if res_set.get("quiet_hours_enabled", True) else "Disabled")
            self.txt_qh_start.setText(res_set.get("quiet_hours_start", "23:00"))
            self.txt_qh_end.setText(res_set.get("quiet_hours_end", "07:00"))
            self.txt_brief_time.setText(res_set.get("daily_briefing_time", "08:30"))
            self.txt_timezone.setText(res_set.get("system_timezone", "Asia/Kolkata"))

        # 4. Load Notification History
        res_notif = self.ipc_call("schedule.list_notifications", {"limit": 40})
        if res_notif and "notifications" in res_notif:
            self._populate_notifs_table(res_notif["notifications"])

        # 5. Check Focus Status
        self._refresh_focus_status()

    def _populate_events_table(self, events: List[Dict[str, Any]]) -> None:
        self.table_events.setRowCount(len(events))
        for row_idx, ev in enumerate(events):
            item_title = QTableWidgetItem(ev.get("title", ""))
            item_title.setData(Qt.UserRole, ev.get("id"))
            self.table_events.setItem(row_idx, 0, item_title)
            self.table_events.setItem(row_idx, 1, QTableWidgetItem(ev.get("category", "")))
            self.table_events.setItem(row_idx, 2, QTableWidgetItem(ev.get("priority", "")))
            self.table_events.setItem(row_idx, 3, QTableWidgetItem(ev.get("event_date", "")))
            self.table_events.setItem(row_idx, 4, QTableWidgetItem(ev.get("start_time") or "all-day"))
            self.table_events.setItem(row_idx, 5, QTableWidgetItem(ev.get("completion_status", "")))

    def _populate_notifs_table(self, notifs: List[Dict[str, Any]]) -> None:
        self.table_notifs.setRowCount(len(notifs))
        for row_idx, n in enumerate(notifs):
            self.table_notifs.setItem(row_idx, 0, QTableWidgetItem(n.get("title", "")))
            self.table_notifs.setItem(row_idx, 1, QTableWidgetItem(n.get("channel", "")))
            self.table_notifs.setItem(row_idx, 2, QTableWidgetItem(n.get("delivery_status", "")))
            self.table_notifs.setItem(row_idx, 3, QTableWidgetItem(n.get("dispatched_at_utc", "")))

    def _on_filter_changed(self) -> None:
        self._load_data()

    def _on_add_event_clicked(self) -> None:
        # Prompt for title and date
        dlg = QDialog(self)
        dlg.setWindowTitle("New Timetable Event")
        f_layout = QFormLayout(dlg)

        inp_title = QLineEdit(dlg)
        f_layout.addRow("Title:", inp_title)

        inp_date = QLineEdit(dlg)
        from datetime import date
        inp_date.setText(date.today().isoformat())
        f_layout.addRow("Date (YYYY-MM-DD):", inp_date)

        inp_time = QLineEdit(dlg)
        inp_time.setPlaceholderText("09:00 (optional)")
        f_layout.addRow("Time (HH:MM):", inp_time)

        inp_cat = QComboBox(dlg)
        inp_cat.addItems(["GENERAL_TASKS", "COLLEGE", "EXAMS", "ASSIGNMENTS", "PROJECTS", "PERSONAL", "MEETINGS"])
        f_layout.addRow("Category:", inp_cat)

        inp_pri = QComboBox(dlg)
        inp_pri.addItems(["MEDIUM", "LOW", "HIGH", "URGENT"])
        f_layout.addRow("Priority:", inp_pri)

        btn_box = QHBoxLayout()
        btn_ok = QPushButton("Schedule", dlg)
        btn_ok.clicked.connect(dlg.accept)
        btn_box.addWidget(btn_ok)
        f_layout.addRow("", btn_box)

        if dlg.exec() == QDialog.Accepted and inp_title.text().strip():
            if self.ipc_call:
                res = self.ipc_call(
                    "schedule.create_event",
                    {
                        "title": inp_title.text().strip(),
                        "event_date": inp_date.text().strip(),
                        "start_time": inp_time.text().strip() or None,
                        "category": inp_cat.currentText(),
                        "priority": inp_pri.currentText(),
                    },
                )
                if res and res.get("success"):
                    self._load_data()

    def _on_delete_event_clicked(self) -> None:
        selected = self.table_events.selectedItems()
        if not selected:
            QMessageBox.information(self, "Delete Event", "Please select an event row to delete.")
            return

        row = selected[0].row()
        ev_id = self.table_events.item(row, 0).data(Qt.UserRole)
        title = self.table_events.item(row, 0).text()

        confirm = QMessageBox.question(
            self,
            "Confirm Delete",
            f"Are you sure you want to delete event '{title}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm == QMessageBox.Yes and self.ipc_call:
            res = self.ipc_call("schedule.delete_event", {"event_id": ev_id})
            if res and res.get("success"):
                self._load_data()

    def _on_start_focus_clicked(self) -> None:
        task = self.txt_focus_task.text().strip()
        if not task:
            QMessageBox.warning(self, "Focus Session", "Please enter a task objective.")
            return

        mins = self.spin_focus_mins.value()
        if self.ipc_call:
            res = self.ipc_call("schedule.start_focus", {"task_focus": task, "duration_minutes": mins})
            if res and res.get("success"):
                self._refresh_focus_status()

    def _on_stop_focus_clicked(self) -> None:
        if self.ipc_call:
            self.ipc_call("schedule.stop_focus", {})
            self._refresh_focus_status()

    def _refresh_focus_status(self) -> None:
        if not self.ipc_call:
            return
        res = self.ipc_call("schedule.get_focus_status", {})
        if res and res.get("active"):
            rem = res.get("remaining_minutes", 0.0)
            task = res.get("task_focus", "")
            self.lbl_focus_status.setText(f"Active Deep Work: '{task}' ({rem:.1f} mins remaining)")
            self.lbl_focus_status.setStyleSheet("font-size: 14px; font-weight: bold; color: #00ff88;")
            self.btn_stop_focus.setEnabled(True)
        else:
            self.lbl_focus_status.setText("No active focus session.")
            self.lbl_focus_status.setStyleSheet("font-size: 14px; font-weight: bold; color: #94a3b8;")
            self.btn_stop_focus.setEnabled(False)

    def _on_save_settings_clicked(self) -> None:
        if not self.ipc_call:
            return
        updates = {
            "quiet_hours_enabled": self.combo_qh_enabled.currentText() == "Enabled",
            "quiet_hours_start": self.txt_qh_start.text().strip(),
            "quiet_hours_end": self.txt_qh_end.text().strip(),
            "daily_briefing_time": self.txt_brief_time.text().strip(),
        }
        res = self.ipc_call("schedule.update_settings", updates)
        if res and res.get("success"):
            QMessageBox.information(self, "Settings Saved", "Schedule and quiet hours settings updated.")

    def _on_clear_notifs_clicked(self) -> None:
        if self.ipc_call:
            self.ipc_call("schedule.clear_notifications", {})
            self._load_data()
