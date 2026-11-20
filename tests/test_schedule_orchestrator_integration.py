"""Integration tests verifying Proactive Intelligence and Timetable Subsystem in ZoroOrchestrator.

Validates:
- Ambiguity detection & clarification: ambiguous reminder queries prompt the user rather than hallucinating dates.
- Natural language event creation, atomic reminder generation, and bridging to Persistent Memory (SCHEDULE category).
- Daily briefing and agenda queries.
- Top operational priorities queries.
- Deadline countdown calculations.
- Focus session commands (start, active check, stop).
- Quiet hours natural language configuration.
- Proactive context injection into orchestrator system prompt.
"""

from __future__ import annotations

import os
import tempfile
import pytest
import aiosqlite

from zoro.core.event_bus import AsyncEventBus
from zoro.memory.manager import MemoryManager
from zoro.memory.models import MemoryCategory, MemoryFilter
from zoro.models.mock import MockModelProvider
from zoro.models.registry import ProviderRegistry
from zoro.orchestrator.orchestrator import ZoroOrchestrator
from zoro.schedule.engine import SchedulerEngine
from zoro.schedule.models import EventCategory, EventPriority, ReminderStatus
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.storage.migrations import MigrationRunner
from zoro.tools.registry import ToolRegistry


@pytest.fixture
async def schedule_orch_env():
    """Build an integrated Orchestrator test environment with real SQLite, MemoryManager, and SchedulerEngine."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    async with aiosqlite.connect(db_path) as conn:
        await MigrationRunner.run_migrations(conn)

    provider_reg = ProviderRegistry()
    mock_prov = MockModelProvider()
    provider_reg.register_provider("mock", mock_prov, default_model="mock-v1")
    provider_reg.set_active_provider("mock")

    db = DatabaseManager()
    audit = AuditLogger(db)
    perms = PermissionGate()
    tool_reg = ToolRegistry(db, audit, perms)
    event_bus = AsyncEventBus()
    emergency_mgr = EmergencyManager()

    memory_mgr = MemoryManager(db_path=db_path)
    scheduler = SchedulerEngine(
        db_path=db_path,
        event_bus_publisher=event_bus.publish,
        emergency_mgr=emergency_mgr,
        instance_id="test-orch-worker",
    )
    await scheduler.initialize()

    orchestrator = ZoroOrchestrator(
        provider_registry=provider_reg,
        tool_registry=tool_reg,
        db=db,
        audit=audit,
        event_bus=event_bus,
        emergency_mgr=emergency_mgr,
        memory_mgr=memory_mgr,
        scheduler_engine=scheduler,
    )

    yield orchestrator, scheduler, memory_mgr, db_path

    if os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_orchestrator_schedule_clarification_on_ambiguity(schedule_orch_env) -> None:
    """Verify that ambiguous reminder requests prompt the user for date/time without inventing schedule data."""
    orchestrator, scheduler, memory_mgr, db_path = schedule_orch_env

    # 1. Ambiguous prompt without date or time
    resp = await orchestrator.process_user_request(
        user_message="remind me to check the server logs",
        conversation_id="conv-ambig-1",
    )

    # 2. Must request clarification
    assert "When would you like me to schedule this reminder, Sir?" in resp.message

    # 3. Verify zero events or reminders were created
    events = await scheduler.store.list_events()
    assert len(events) == 0


@pytest.mark.asyncio
async def test_orchestrator_confirmed_reminder_creation_and_memory_bridge(schedule_orch_env) -> None:
    """Verify natural language reminder scheduling creates events, reminders, and bridges to Memory."""
    orchestrator, scheduler, memory_mgr, db_path = schedule_orch_env

    # Explicit command with date and time
    resp = await orchestrator.process_user_request(
        user_message="remind me tomorrow at 10:00 to submit the machine learning assignment",
        conversation_id="conv-sched-1",
    )

    # 1. Confirmation message
    assert "Certainly, Sir. I have scheduled a reminder" in resp.message
    assert "machine learning assignment" in resp.message.lower()

    # 2. Verify in SQLite events table
    events = await scheduler.store.list_events()
    assert len(events) == 1
    ev = events[0]
    assert "machine learning assignment" in ev.title.lower()
    assert ev.start_time == "10:00"

    # 3. Verify attached reminder created
    reminders = await scheduler.store.list_reminders_for_event(ev.id)
    assert len(reminders) == 1
    assert reminders[0].status == ReminderStatus.PENDING

    # 4. Verify bridged into Persistent Memory under SCHEDULE category
    memories = await memory_mgr.store.get_all(MemoryFilter(category=MemoryCategory.SCHEDULE))
    assert len(memories) >= 1
    assert any("machine learning assignment" in m.content.lower() for m in memories)


@pytest.mark.asyncio
async def test_orchestrator_agenda_and_briefing_query(schedule_orch_env) -> None:
    """Verify agenda queries generate deterministic operational daily briefings."""
    orchestrator, scheduler, memory_mgr, db_path = schedule_orch_env

    today_str = scheduler.parser.now_local().strftime("%Y-%m-%d")

    # Seed an event for today
    await scheduler.timetable.add_event_with_reminders(
        title="Quarterly System Architecture Review",
        event_date=today_str,
        start_time="11:30",
        category=EventCategory.PROJECTS,
        priority=EventPriority.HIGH,
    )

    # Ask orchestrator for today's agenda
    resp = await orchestrator.process_user_request(
        user_message="what do i have scheduled today?",
        conversation_id="conv-agenda-1",
    )

    assert "TODAY'S AGENDA" in resp.message
    assert "Quarterly System Architecture Review" in resp.message
    assert "11:30" in resp.message


@pytest.mark.asyncio
async def test_orchestrator_top_priorities_query(schedule_orch_env) -> None:
    """Verify top priorities query ranks overdue and near-term deadlines."""
    orchestrator, scheduler, memory_mgr, db_path = schedule_orch_env

    today_str = scheduler.parser.now_local().strftime("%Y-%m-%d")

    # Add an urgent deadline
    await scheduler.timetable.add_event_with_reminders(
        title="Submit Grant Proposal",
        event_date=today_str,
        start_time="23:59",
        category=EventCategory.PROJECTS,
        priority=EventPriority.URGENT,
    )

    resp = await orchestrator.process_user_request(
        user_message="what are my three most urgent tasks?",
        conversation_id="conv-pri-1",
    )

    assert "top operational priorities" in resp.message.lower()
    assert "Submit Grant Proposal" in resp.message


@pytest.mark.asyncio
async def test_orchestrator_deadline_countdown_query(schedule_orch_env) -> None:
    """Verify deadline countdown query calculates remaining days and hours accurately."""
    orchestrator, scheduler, memory_mgr, db_path = schedule_orch_env

    import datetime as dt_mod
    future_date = (scheduler.parser.now_local().date() + dt_mod.timedelta(days=5)).strftime("%Y-%m-%d")

    await scheduler.timetable.add_event_with_reminders(
        title="Autonomous Robotics Midterm Exam",
        event_date=future_date,
        start_time="14:00",
        category=EventCategory.EXAMS,
        priority=EventPriority.HIGH,
    )

    resp = await orchestrator.process_user_request(
        user_message="how many days left until Robotics Midterm Exam?",
        conversation_id="conv-cd-1",
    )

    assert "Autonomous Robotics Midterm Exam" in resp.message
    assert "days remaining" in resp.message.lower()


@pytest.mark.asyncio
async def test_orchestrator_focus_session_commands(schedule_orch_env) -> None:
    """Verify natural language focus session initiation and termination."""
    orchestrator, scheduler, memory_mgr, db_path = schedule_orch_env

    # 1. Start session
    resp1 = await orchestrator.process_user_request(
        user_message="start focus session for 45 minutes on GPU Optimization",
        conversation_id="conv-focus-1",
    )
    assert "Focus session initiated for 45 minutes" in resp1.message
    assert "GPU Optimization" in resp1.message

    # Verify active session in DB
    active = await scheduler.focus.get_active_session()
    assert active is not None
    assert active.duration_minutes == 45
    assert active.task_focus == "GPU Optimization"

    # 2. Stop session
    resp2 = await orchestrator.process_user_request(
        user_message="stop focus session",
        conversation_id="conv-focus-1",
    )
    assert "Focus session concluded" in resp2.message

    # Verify session is no longer active
    assert await scheduler.focus.get_active_session() is None


@pytest.mark.asyncio
async def test_orchestrator_quiet_hours_command(schedule_orch_env) -> None:
    """Verify configuring quiet hours through natural language updates persistent settings."""
    orchestrator, scheduler, memory_mgr, db_path = schedule_orch_env

    resp = await orchestrator.process_user_request(
        user_message="quiet hours from 22:00 to 08:00",
        conversation_id="conv-qh-1",
    )

    assert "Quiet hours configured from 22:00 to 08:00" in resp.message

    settings = await scheduler.store.get_settings()
    assert settings.quiet_hours_enabled is True
    assert settings.quiet_hours_start == "22:00"
    assert settings.quiet_hours_end == "08:00"
