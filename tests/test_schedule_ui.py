"""UI tests for PROJECT ZORO Milestone 06 Timetable, Deadlines, and Focus Mode Panel."""

from __future__ import annotations

import sys
import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication

from zoro.ui.timetable_panel import ZoroTimetableDialog


@pytest.fixture(scope="module")
def qapp():
    """Ensure QApplication instance is initialized."""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_timetable_dialog_initialization(qapp) -> None:
    """Verify ZoroTimetableDialog initializes with all 5 tabs and widgets without errors."""
    dlg = ZoroTimetableDialog(ipc_call_handler=None)
    try:
        assert dlg.tabs.count() == 5
        assert dlg.tabs.tabText(0) == "Agenda & Deadlines"
        assert dlg.tabs.tabText(1) == "Timetable Events"
        assert dlg.tabs.tabText(2) == "Focus Mode"
        assert dlg.tabs.tabText(3) == "Quiet Hours & Settings"
        assert dlg.tabs.tabText(4) == "Alert History"

        assert dlg.txt_briefing is not None
        assert dlg.table_events is not None
        assert dlg.table_notifs is not None
        assert dlg.btn_start_focus is not None
    finally:
        dlg.close()


def test_timetable_dialog_table_population_from_ipc(qapp) -> None:
    """Verify ZoroTimetableDialog populates events and briefing from IPC responses."""
    mock_ipc = MagicMock()

    def ipc_side_effect(method: str, params: dict):
        if method == "schedule.get_briefing":
            return {
                "success": True,
                "briefing": {
                    "summary_text": "Good morning, Sir. Today's Agenda:\n• [EXAMS] Final Exam at 09:00",
                },
            }
        elif method == "schedule.list_events":
            return {
                "success": True,
                "events": [
                    {
                        "id": "ev-101",
                        "title": "Autonomous Systems Final Exam",
                        "category": "EXAMS",
                        "priority": "URGENT",
                        "event_date": "2026-12-15",
                        "start_time": "09:00",
                        "completion_status": "PENDING",
                    },
                    {
                        "id": "ev-102",
                        "title": "Machine Learning Lab Presentation",
                        "category": "PROJECTS",
                        "priority": "HIGH",
                        "event_date": "2026-12-16",
                        "start_time": "14:00",
                        "completion_status": "PENDING",
                    },
                ],
            }
        elif method == "schedule.get_focus_status":
            return {
                "success": True,
                "active": True,
                "task_focus": "GPU Optimization",
                "remaining_minutes": 32.5,
            }
        elif method == "schedule.get_settings":
            return {
                "success": True,
                "settings": {
                    "system_timezone": "Asia/Kolkata",
                    "quiet_hours_enabled": True,
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "08:00",
                    "daily_briefing_time": "08:00",
                },
            }
        elif method == "schedule.list_notifications":
            return {
                "success": True,
                "notifications": [
                    {
                        "id": "notif-1",
                        "title": "Exam Reminder",
                        "channel": "SYSTEM_TRAY",
                        "delivery_status": "SUCCESS",
                        "dispatched_at_utc": "2026-12-15T03:30:00Z",
                    }
                ],
            }
        return {"success": True}

    mock_ipc.side_effect = ipc_side_effect

    dlg = ZoroTimetableDialog(ipc_call_handler=mock_ipc)
    try:
        # Check briefing loaded
        assert "Autonomous Systems Final Exam" in dlg.txt_briefing.toPlainText() or "Final Exam" in dlg.txt_briefing.toPlainText()

        # Check events table populated
        assert dlg.table_events.rowCount() == 2
        assert dlg.table_events.item(0, 0).text() == "Autonomous Systems Final Exam"
        assert dlg.table_events.item(0, 1).text() == "EXAMS"
        assert dlg.table_events.item(0, 2).text() == "URGENT"

        assert dlg.table_events.item(1, 0).text() == "Machine Learning Lab Presentation"
        assert dlg.table_events.item(1, 1).text() == "PROJECTS"

        # Check focus monitor updated
        assert "GPU Optimization" in dlg.lbl_focus_status.text()
        assert dlg.btn_stop_focus.isEnabled() is True

        # Check settings loaded
        assert dlg.combo_qh_enabled.currentText() == "Enabled"
        assert dlg.txt_qh_start.text() == "22:00"
        assert dlg.txt_qh_end.text() == "08:00"

        # Check notification history table populated
        assert dlg.table_notifs.rowCount() == 1
        assert dlg.table_notifs.item(0, 0).text() == "Exam Reminder"
        assert dlg.table_notifs.item(0, 1).text() == "SYSTEM_TRAY"
    finally:
        dlg.close()


def test_timetable_dialog_focus_session_actions(qapp) -> None:
    """Verify starting and stopping a focus session invokes the expected IPC calls."""
    mock_ipc = MagicMock()
    mock_ipc.return_value = {"success": True}

    dlg = ZoroTimetableDialog(ipc_call_handler=mock_ipc)
    try:
        dlg.txt_focus_task.setText("Kernel Driver Debugging")
        dlg.spin_focus_mins.setValue(50)

        # Trigger start focus
        dlg.btn_start_focus.click()
        mock_ipc.assert_any_call(
            "schedule.start_focus",
            {"task_focus": "Kernel Driver Debugging", "duration_minutes": 50},
        )

        # Trigger stop focus
        dlg.btn_stop_focus.setEnabled(True)
        dlg.btn_stop_focus.click()
        mock_ipc.assert_any_call("schedule.stop_focus", {})
    finally:
        dlg.close()
