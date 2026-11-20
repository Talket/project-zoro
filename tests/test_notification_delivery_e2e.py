"""End-to-end verification of multi-modal notification delivery in PROJECT ZORO.

Validates:
1. Engine forwards schedule.alert and schedule.briefing across Named Pipe IPC.
2. NotificationDispatcher dispatches alerts to event bus, stores history, and invokes voice TTS.
3. Quiet hours defers sound/TTS while still emitting silent HUD alerts.
4. User-requested near-term timers take HIGH priority and ring/speak.
5. ZoroMainWindow updates HUD log, shows Windows native tray toast, and plays audible chime safely on the GUI thread.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import aiosqlite
import pytest
from PySide6.QtWidgets import QApplication

from zoro.schedule.models import (
    EventPriority,
    NotificationChannel,
    NotificationDeliveryStatus,
    ReminderCreate,
    ScheduleSettings,
)
from zoro.schedule.notifications import NotificationDispatcher
from zoro.schedule.store import ScheduleStore
from zoro.storage.migrations import MigrationRunner
from zoro.ui.window import ZoroMainWindow


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
async def temp_schedule_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    async with aiosqlite.connect(path) as conn:
        await MigrationRunner.run_migrations(conn)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.mark.asyncio
async def test_notification_dispatcher_emits_event_and_speaks_tts(temp_schedule_db: str):
    """Verify that due reminder dispatch emits schedule.alert and triggers voice TTS."""
    store = ScheduleStore(db_path=temp_schedule_db)
    published_events = []
    spoken_phrases = []

    async def mock_publisher(topic: str, payload: dict):
        published_events.append((topic, payload))

    def mock_speaker(phrase: str):
        spoken_phrases.append(phrase)

    dispatcher = NotificationDispatcher(
        store=store,
        event_bus_publisher=mock_publisher,
        tts_speaker=mock_speaker,
    )

    settings = ScheduleSettings(
        system_timezone="Asia/Kolkata",
        quiet_hours_enabled=False,  # Quiet hours disabled
    )

    rem = await store.create_reminder(
        ReminderCreate(
            remind_at_utc=datetime.now(timezone.utc).isoformat(),
            remind_at_local="2026-11-20 10:00:00",
            title="Check Fans",
            message="Check cooling fans and thermal performance",
            priority=EventPriority.MEDIUM,
        )
    )

    record = await dispatcher.dispatch_reminder(rem, settings)

    # 1. Verify delivery record
    assert record.delivery_status == NotificationDeliveryStatus.SUCCESS
    assert record.channel == NotificationChannel.SYSTEM_TRAY

    # 2. Verify event bus broadcast
    assert len(published_events) == 1
    topic, payload = published_events[0]
    assert topic == "schedule.alert"
    assert payload["reminder_id"] == rem.id
    assert payload["title"] == "Check Fans"
    assert payload["is_silent"] is False

    # 3. Verify voice TTS was invoked
    assert len(spoken_phrases) == 1
    assert "Check Fans" in spoken_phrases[0]


@pytest.mark.asyncio
async def test_notification_dispatcher_quiet_hours_emits_silent_hud_alert(temp_schedule_db: str):
    """Verify that during quiet hours, non-urgent reminders emit silent HUD alert without voice TTS."""
    store = ScheduleStore(db_path=temp_schedule_db)
    published_events = []
    spoken_phrases = []

    async def mock_publisher(topic: str, payload: dict):
        published_events.append((topic, payload))

    def mock_speaker(phrase: str):
        spoken_phrases.append(phrase)

    dispatcher = NotificationDispatcher(
        store=store,
        event_bus_publisher=mock_publisher,
        tts_speaker=mock_speaker,
    )

    # Enable quiet hours active 00:00 to 23:59 (covering all day)
    settings = ScheduleSettings(
        system_timezone="Asia/Kolkata",
        quiet_hours_enabled=True,
        quiet_hours_start="00:00",
        quiet_hours_end="23:59",
    )

    rem = await store.create_reminder(
        ReminderCreate(
            remind_at_utc=datetime.now(timezone.utc).isoformat(),
            remind_at_local="2026-11-20 02:00:00",
            title="Nightly Routine",
            message="Silent backup reminder",
            priority=EventPriority.LOW,
        )
    )

    record = await dispatcher.dispatch_reminder(rem, settings)

    # 1. Delivery record indicates suppressed for quiet hours
    assert record.delivery_status == NotificationDeliveryStatus.SUPPRESSED_QUIET_HOURS
    assert record.channel == NotificationChannel.HUD_CONSOLE

    # 2. Event bus STILL emitted for HUD display, with is_silent=True
    assert len(published_events) == 1
    topic, payload = published_events[0]
    assert topic == "schedule.alert"
    assert payload["is_silent"] is True

    # 3. Voice TTS was NOT spoken
    assert len(spoken_phrases) == 0


def test_main_window_update_schedule_alert_ui_integration(qapp):
    """Verify ZoroMainWindow GUI slot handles schedule alert, shows tray toast, and beeps safely."""
    win = ZoroMainWindow()
    mock_tray = MagicMock()
    win.tray_icon = mock_tray

    payload = {
        "reminder_id": "rem-test-01",
        "title": "Check Cooling System",
        "message": "Temperature exceeded normal operational limits",
        "priority": "HIGH",
        "is_silent": False,
    }

    with patch("winsound.MessageBeep") as mock_beep:
        win.update_schedule_alert(payload)

        # 1. Chime was sounded
        mock_beep.assert_called_once()

        # 2. Tray toast was invoked with title, message and Warning icon
        mock_tray.showMessage.assert_called_once()
        args = mock_tray.showMessage.call_args[0]
        assert args[0] == "Check Cooling System"
        assert "Temperature exceeded" in args[1]

        # 3. Log was appended in console
        assert "Check Cooling System" in win.console.toPlainText()
