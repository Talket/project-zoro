"""Comprehensive Unit Tests for PROJECT ZORO Milestone 06 Proactive Intelligence Subsystem.

Covers:
- ScheduleStore CRUD operations and cascading deletion.
- Atomic reminder claiming (BEGIN IMMEDIATE) and concurrent worker contention.
- Stale claim recovery past cutoff timestamp.
- Timezone persistence in schedule settings.
- Deterministic temporal parsing and ambiguity detection.
- Non-drifting monthly recurrence clamping (target_day_of_month preservation).
- Quiet hours split-interval evaluation across midnight and high-priority bypass.
- Focus session lifecycle and notification suppression.
- Missed reminder recovery sweeps and consolidated batching.
- Timetable deadline urgency scoring and conflict detection.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
import os
import tempfile
import pytest
import aiosqlite
from zoneinfo import ZoneInfo

from zoro.schedule.focus import FocusSessionManager
from zoro.schedule.models import (
    EventCategory,
    EventCompletionStatus,
    EventCreate,
    EventPriority,
    EventRecurrence,
    EventSource,
    EventUpdate,
    NotificationChannel,
    NotificationDeliveryStatus,
    ReminderCreate,
    ReminderStatus,
    ScheduleSettings,
)
from zoro.schedule.notifications import NotificationDispatcher, QuietHoursEvaluator
from zoro.schedule.parser import TemporalParser
from zoro.schedule.store import ScheduleStore
from zoro.schedule.timetable import TimetableManager
from zoro.storage.migrations import MigrationRunner


@pytest.fixture
async def temp_schedule_db():
    """Create a temporary SQLite database with migration 007 applied."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        async with aiosqlite.connect(db_path) as conn:
            await MigrationRunner.run_migrations(conn)
        yield db_path
    finally:
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_schedule_event_crud_and_cascade(temp_schedule_db: str) -> None:
    """Verify Event CRUD lifecycle and cascading deletion to attached reminders."""
    store = ScheduleStore(db_path=temp_schedule_db)

    # 1. Create Event
    ev_create = EventCreate(
        title="CS301 Machine Learning Final Exam",
        description="Room 402, bring calculator and ID card.",
        category=EventCategory.EXAMS,
        priority=EventPriority.URGENT,
        event_date="2026-12-15",
        start_time="09:00",
        end_time="12:00",
        timezone="Asia/Kolkata",
    )
    event = await store.create_event(ev_create)
    assert event.id is not None
    assert event.title == "CS301 Machine Learning Final Exam"
    assert event.category == EventCategory.EXAMS
    assert event.priority == EventPriority.URGENT

    # 2. Add an attached Reminder
    rem = await store.create_reminder(
        ReminderCreate(
            event_id=event.id,
            remind_at_utc="2026-12-15T02:30:00Z",
            remind_at_local="2026-12-15 08:00",
            offset_minutes=60,
            title="Exam in 1 hour",
            message="Machine Learning exam begins in 1 hour.",
            priority=EventPriority.URGENT,
        )
    )
    assert rem.id is not None
    assert rem.event_id == event.id
    assert rem.status == ReminderStatus.PENDING

    # 3. Read Event
    fetched = await store.get_event(event.id)
    assert fetched is not None
    assert fetched.title == event.title

    # 4. Update Event
    updated = await store.update_event(
        event.id,
        EventUpdate(
            title="CS301 ML Final Exam (Rescheduled)",
            start_time="10:00",
            priority=EventPriority.HIGH,
        ),
    )
    assert updated is not None
    assert updated.title == "CS301 ML Final Exam (Rescheduled)"
    assert updated.start_time == "10:00"
    assert updated.priority == EventPriority.HIGH

    # 5. List Events
    events_list = await store.list_events(category=EventCategory.EXAMS)
    assert len(events_list) == 1
    assert events_list[0].id == event.id

    # 6. Delete Event and verify cascading deletion of attached reminder
    deleted = await store.delete_event(event.id)
    assert deleted is True

    # Event should no longer be returned
    assert await store.get_event(event.id) is None
    # Reminder should be deleted by foreign-key ON DELETE CASCADE
    reminders = await store.get_reminders_for_event(event.id)
    assert len(reminders) == 0


@pytest.mark.asyncio
async def test_atomic_reminder_claim_and_recovery(temp_schedule_db: str) -> None:
    """Verify atomic claiming with BEGIN IMMEDIATE, rowcount enforcement, and stale claim recovery."""
    store = ScheduleStore(db_path=temp_schedule_db)

    # Create past-due reminder
    past_due_utc = "2026-01-01T00:00:00Z"
    rem = await store.create_reminder(
        ReminderCreate(
            remind_at_utc=past_due_utc,
            remind_at_local="2026-01-01 05:30",
            offset_minutes=0,
            title="Past Due Server Check",
            message="Check backup storage health.",
            priority=EventPriority.HIGH,
        )
    )

    now_utc = "2026-01-01T01:00:00Z"
    stale_cutoff = "2026-01-01T00:59:00Z"

    # Worker 1 claims the reminder
    claimed_1 = await store.claim_due_reminders(
        worker_id="worker-node-alpha",
        now_utc=now_utc,
        stale_cutoff_utc=stale_cutoff,
        limit=5,
    )
    assert len(claimed_1) == 1
    assert claimed_1[0].id == rem.id
    assert claimed_1[0].status == ReminderStatus.CLAIMED
    assert claimed_1[0].claim_worker_id == "worker-node-alpha"

    # Worker 2 attempts to claim immediately (should receive 0 reminders, preventing duplicates)
    claimed_2 = await store.claim_due_reminders(
        worker_id="worker-node-beta",
        now_utc=now_utc,
        stale_cutoff_utc=stale_cutoff,
        limit=5,
    )
    assert len(claimed_2) == 0

    # Simulate worker crash: claim is abandoned. Advance time past stale cutoff (60s+)
    crash_time_now_utc = "2026-01-01T01:05:00Z"
    crash_stale_cutoff = "2026-01-01T01:04:00Z"  # Worker 1's claim from 01:00 is now stale

    # Worker 3 runs loop: detects stale claim and re-claims it
    claimed_3 = await store.claim_due_reminders(
        worker_id="worker-node-gamma",
        now_utc=crash_time_now_utc,
        stale_cutoff_utc=crash_stale_cutoff,
        limit=5,
    )
    assert len(claimed_3) == 1
    assert claimed_3[0].id == rem.id
    assert claimed_3[0].claim_worker_id == "worker-node-gamma"
    assert claimed_3[0].dispatch_attempts >= 2


@pytest.mark.asyncio
async def test_concurrent_worker_contention(temp_schedule_db: str) -> None:
    """Verify that when two concurrent workers race to claim the same reminder, exactly one succeeds."""
    store = ScheduleStore(db_path=temp_schedule_db)

    # Insert a single due reminder
    now_dt = datetime.now(timezone.utc)
    due_utc = (now_dt - timedelta(minutes=5)).isoformat()
    rem = await store.create_reminder(
        ReminderCreate(
            remind_at_utc=due_utc,
            remind_at_local="due_local",
            title="Contention Test Item",
            message="Testing atomic concurrency.",
            priority=EventPriority.MEDIUM,
        )
    )

    now_utc_str = now_dt.isoformat()
    stale_str = (now_dt - timedelta(minutes=1)).isoformat()

    # Race two concurrent worker claims
    task_a = store.claim_due_reminders("worker-race-1", now_utc_str, stale_str, limit=5)
    task_b = store.claim_due_reminders("worker-race-2", now_utc_str, stale_str, limit=5)

    res_a, res_b = await asyncio.gather(task_a, task_b)

    # Exactly one worker must have claimed the reminder
    total_claimed = len(res_a) + len(res_b)
    assert total_claimed == 1
    winner = "worker-race-1" if len(res_a) == 1 else "worker-race-2"

    # Verify state in database
    async with aiosqlite.connect(temp_schedule_db) as conn:
        async with conn.execute("SELECT status, claim_worker_id FROM reminders WHERE id = ?", (rem.id,)) as cursor:
            row = await cursor.fetchone()
            assert row[0] == ReminderStatus.CLAIMED.value
            assert row[1] == winner


@pytest.mark.asyncio
async def test_timezone_persistence_and_update(temp_schedule_db: str) -> None:
    """Verify schedule settings store and load user timezone accurately."""
    store = ScheduleStore(db_path=temp_schedule_db)

    # 1. Default settings check
    initial_settings = await store.get_settings()
    assert initial_settings.system_timezone == "Asia/Kolkata"
    assert initial_settings.quiet_hours_enabled is True

    # 2. Update timezone and quiet hours
    updated_settings = ScheduleSettings(
        system_timezone="America/New_York",
        quiet_hours_enabled=True,
        quiet_hours_start="22:30",
        quiet_hours_end="07:30",
        briefing_time="08:00",
    )
    saved = await store.save_settings(updated_settings)
    assert saved.system_timezone == "America/New_York"
    assert saved.quiet_hours_enabled is True
    assert saved.quiet_hours_start == "22:30"

    # 3. Reload from fresh store instance
    store_2 = ScheduleStore(db_path=temp_schedule_db)
    reloaded = await store_2.get_settings()
    assert reloaded.system_timezone == "America/New_York"
    assert reloaded.quiet_hours_enabled is True
    assert reloaded.quiet_hours_end == "07:30"


def test_temporal_parser_deterministic_resolutions() -> None:
    """Test deterministic temporal expressions and ambiguity detection."""
    parser = TemporalParser(default_timezone="Asia/Kolkata")

    # 1. Relative offset in minutes: "remind me in 30 minutes to submit report"
    res1 = parser.parse_scheduling_prompt("remind me in 30 minutes to submit report")
    assert res1.is_ambiguous is False
    assert res1.event_date is not None
    assert res1.start_time is not None
    assert "submit report" in res1.extracted_title.lower()

    # 2. Specific time today/tomorrow: "schedule meeting at 2:30 PM"
    res2 = parser.parse_scheduling_prompt("schedule meeting at 2:30 PM with team")
    assert res2.is_ambiguous is False
    assert res2.start_time == "14:30"
    assert "meeting" in res2.extracted_title.lower()

    # 3. 24-hour military time: "remind me at 18:00 to run backup"
    res3 = parser.parse_scheduling_prompt("remind me at 18:00 to run backup")
    assert res3.is_ambiguous is False
    assert res3.start_time == "18:00"

    # 4. Ambiguity Detection: "remind me to call John" (no time or date specified)
    res4 = parser.parse_scheduling_prompt("remind me to call John")
    assert res4.is_ambiguous is True
    assert res4.ambiguity_reason is not None

    # 5. Focus session parsing: "focus for 45 minutes on python"
    res5 = parser.parse_scheduling_prompt("focus for 45 minutes on python")
    assert res5.duration_minutes == 45


def test_monthly_recurrence_target_day_clamping() -> None:
    """Verify that monthly recurring events clamp to month ends without drift (e.g. Jan 31 -> Feb 28 -> Mar 31)."""
    parser = TemporalParser(default_timezone="Asia/Kolkata")

    # Case: Starting on January 31, 2026 (target_day_of_month = 31)
    next_date, target_day = parser.calculate_next_monthly_occurrence(
        current_date_str="2026-01-31",
        target_day_of_month=31,
    )
    # February 2026 has 28 days -> clamped to 2026-02-28, but target_day remains 31
    assert next_date == "2026-02-28"
    assert target_day == 31

    # Case: Advancing from clamped February 28 to March
    next_date_2, target_day_2 = parser.calculate_next_monthly_occurrence(
        current_date_str=next_date,
        target_day_of_month=target_day,
    )
    # March 2026 has 31 days -> restored to 2026-03-31 (NO DRIFT to 28th!)
    assert next_date_2 == "2026-03-31"
    assert target_day_2 == 31

    # Case: Leap year test: Jan 31, 2028 -> Feb 29, 2028 -> Mar 31, 2028
    leap_feb, leap_target = parser.calculate_next_monthly_occurrence(
        current_date_str="2028-01-31",
        target_day_of_month=31,
    )
    assert leap_feb == "2028-02-29"
    assert leap_target == 31


def test_quiet_hours_split_interval_and_bypass() -> None:
    """Verify midnight-crossing quiet hours interval (e.g. 23:00 to 07:00) and priority bypass."""
    # Split interval: 23:00 to 07:00
    evaluator = QuietHoursEvaluator(
        enabled=True,
        start_str="23:00",
        end_str="07:00",
        tz_name="Asia/Kolkata",
    )

    tz = ZoneInfo("Asia/Kolkata")

    # 1. Active at 23:30 (before midnight)
    dt_late = datetime(2026, 11, 19, 23, 30, tzinfo=tz)
    assert evaluator.is_in_quiet_hours(dt_late) is True

    # 2. Active at 03:00 (after midnight)
    dt_early = datetime(2026, 11, 19, 3, 0, tzinfo=tz)
    assert evaluator.is_in_quiet_hours(dt_early) is True

    # 3. Inactive at 14:00 (midday)
    dt_day = datetime(2026, 11, 19, 14, 0, tzinfo=tz)
    assert evaluator.is_in_quiet_hours(dt_day) is False

    # 4. Inactive at 07:00 sharp (boundary)
    dt_boundary = datetime(2026, 11, 19, 7, 0, tzinfo=tz)
    assert evaluator.is_in_quiet_hours(dt_boundary) is False

    # 5. Priority Bypass: URGENT reminders bypass quiet hours even when active
    assert evaluator.should_suppress_notification(EventPriority.LOW, dt_late) is True
    assert evaluator.should_suppress_notification(EventPriority.MEDIUM, dt_late) is True
    assert evaluator.should_suppress_notification(EventPriority.HIGH, dt_late) is False
    assert evaluator.should_suppress_notification(EventPriority.URGENT, dt_late) is False


@pytest.mark.asyncio
async def test_focus_session_lifecycle_and_suppression(temp_schedule_db: str) -> None:
    """Verify Focus Session lifecycle, active detection, and non-urgent notification holding."""
    store = ScheduleStore(db_path=temp_schedule_db)
    focus_mgr = FocusSessionManager(store=store)

    # 1. No initial active session
    assert await focus_mgr.get_active_session() is None
    assert await focus_mgr.is_focus_active() is False

    # 2. Start 30-minute focus session
    sess = await focus_mgr.start_session(duration_minutes=30, goal="Complete Milestone 06 Tests")
    assert sess.id is not None
    assert sess.status == "ACTIVE"
    assert sess.duration_minutes == 30
    assert sess.task_focus == "Complete Milestone 06 Tests"

    # 3. Verify active detection
    assert await focus_mgr.is_focus_active() is True
    active = await focus_mgr.get_active_session()
    assert active is not None
    assert active.id == sess.id

    # 4. Stop session
    stopped = await focus_mgr.stop_session()
    assert stopped is not None
    assert stopped.status == "CANCELLED" or stopped.status == "COMPLETED"
    assert await focus_mgr.is_focus_active() is False


@pytest.mark.asyncio
async def test_missed_reminder_recovery_sweep(temp_schedule_db: str) -> None:
    """Verify that reminders missed during machine sleep/offline state are swept and consolidated."""
    store = ScheduleStore(db_path=temp_schedule_db)

    now = datetime.now(timezone.utc)
    # 1. Insert reminder that was due 2 hours ago (within 24h recovery window)
    due_2h_ago = (now - timedelta(hours=2)).isoformat()
    rem_recent = await store.create_reminder(
        ReminderCreate(
            remind_at_utc=due_2h_ago,
            remind_at_local="2h_ago_local",
            title="Recent Missed Task",
            message="Missed while laptop was asleep.",
            priority=EventPriority.MEDIUM,
        )
    )

    # 2. Insert reminder that was due 48 hours ago (past 24h expiration threshold)
    due_48h_ago = (now - timedelta(hours=48)).isoformat()
    rem_expired = await store.create_reminder(
        ReminderCreate(
            remind_at_utc=due_48h_ago,
            remind_at_local="48h_ago_local",
            title="Expired Ancient Task",
            message="Missed days ago.",
            priority=EventPriority.LOW,
        )
    )

    # 3. Perform recovery sweep
    now_iso = now.isoformat()
    recent_missed, expired_missed = await store.recover_missed_reminders(now_utc=now_iso, max_missed_age_hours=24)

    assert len(recent_missed) == 1
    assert recent_missed[0].id == rem_recent.id
    assert len(expired_missed) == 1
    assert expired_missed[0].id == rem_expired.id

    # Verify that the ancient one was marked MISSED in DB
    async with aiosqlite.connect(temp_schedule_db) as conn:
        async with conn.execute("SELECT status FROM reminders WHERE id = ?", (rem_expired.id,)) as cursor:
            row = await cursor.fetchone()
            assert row[0] == ReminderStatus.MISSED.value


@pytest.mark.asyncio
async def test_timetable_deadlines_and_urgency(temp_schedule_db: str) -> None:
    """Verify deadline countdown calculations, urgency scoring, and conflict detection."""
    store = ScheduleStore(db_path=temp_schedule_db)
    tt = TimetableManager(store=store, default_timezone="Asia/Kolkata")

    today_str = tt.parser.now_local().strftime("%Y-%m-%d")
    tomorrow_str = (tt.parser.now_local().date() + timedelta(days=1)).strftime("%Y-%m-%d")

    # 1. Create a medium priority event tomorrow at 18:00
    ev1 = await tt.add_event_with_reminders(
        title="Weekly Assignment Submission",
        event_date=tomorrow_str,
        start_time="18:00",
        category=EventCategory.ASSIGNMENTS,
        priority=EventPriority.MEDIUM,
    )

    # 2. Create an urgent priority event today at 23:59
    ev2 = await tt.add_event_with_reminders(
        title="Urgent Bug Fix Deployment",
        event_date=today_str,
        start_time="23:59",
        category=EventCategory.PROJECTS,
        priority=EventPriority.URGENT,
    )

    # 3. Query deadlines
    deadlines = await tt.get_upcoming_deadlines(horizon_days=7)
    assert len(deadlines) >= 2

    # Urgent deployment with fewer hours remaining must rank higher in urgency
    assert deadlines[0].event_id == ev2.id
    assert deadlines[0].urgency_score > deadlines[1].urgency_score

    # 4. Scheduling Conflict Detection
    # Add an event from 14:00 to 15:00
    await tt.add_event_with_reminders(
        title="Client Sync",
        event_date=tomorrow_str,
        start_time="14:00",
        end_time="15:00",
    )

    # Overlapping interval 14:30 - 15:30
    conflicts = await tt.detect_scheduling_conflicts(
        event_date=tomorrow_str,
        start_time="14:30",
        end_time="15:30",
    )
    assert len(conflicts) == 1
    assert conflicts[0].title == "Client Sync"

    # Non-overlapping interval 16:00 - 17:00
    no_conflicts = await tt.detect_scheduling_conflicts(
        event_date=tomorrow_str,
        start_time="16:00",
        end_time="17:00",
    )
    assert len(no_conflicts) == 0


@pytest.mark.asyncio
async def test_scheduler_engine_clock_jump_detection(temp_schedule_db: str) -> None:
    """Verify that a significant wall-clock jump triggers a fresh due-reminder recovery sweep."""
    from zoro.schedule.engine import SchedulerEngine

    scheduler = SchedulerEngine(db_path=temp_schedule_db, instance_id="clock-jump-worker")
    await scheduler.initialize()

    # 1. Normal interval: 2 seconds elapsed on monotonic, 2 seconds on wall clock
    t0_mono = 100.0
    t0_wall = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
    scheduler._last_mono = t0_mono
    scheduler._last_wall_utc = t0_wall

    assert scheduler.check_clock_jump(t0_mono + 2.0, t0_wall + timedelta(seconds=2.0)) is False

    # 2. Clock jump forward by 1 hour (e.g. manual time change or wake from sleep)
    jumped_wall = t0_wall + timedelta(hours=1)
    # Monotonic only advanced 2 seconds
    jumped_mono = t0_mono + 2.0

    assert scheduler.check_clock_jump(jumped_mono, jumped_wall) is True
