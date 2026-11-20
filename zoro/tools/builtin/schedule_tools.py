"""Built-in Timetable, Reminder, and Proactive Scheduling Tools for PROJECT ZORO."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from zoro.schedule.models import (
    EventCategory,
    EventPriority,
    EventRecurrence,
)
from zoro.schedule.timetable import TimetableManager
from zoro.schedule.focus import FocusSessionManager
from zoro.schedule.briefing import DailyBriefingGenerator
from zoro.schedule.store import ScheduleStore
from zoro.tools.base import BaseTool, ToolContext, ToolPermissionTier


# ---------------------------------------------------------------------------
# 1. Schedule Event Tool (LOW_RISK)
# ---------------------------------------------------------------------------

class ScheduleEventInput(BaseModel):
    title: str = Field(description="Title of the event or task, e.g. 'DAA Assignment Deadline'")
    event_date: str = Field(description="Calendar date in YYYY-MM-DD format")
    start_time: Optional[str] = Field(None, description="Local time in HH:MM format, e.g. '09:00'")
    end_time: Optional[str] = Field(None, description="Local end time in HH:MM format, e.g. '10:30'")
    category: str = Field("GENERAL_TASKS", description="COLLEGE, EXAMS, ASSIGNMENTS, PROJECTS, PERSONAL, MEETINGS, GENERAL_TASKS")
    priority: str = Field("MEDIUM", description="LOW, MEDIUM, HIGH, URGENT")
    recurrence: str = Field("NONE", description="NONE, DAILY, WEEKLY, WEEKDAYS, MONTHLY")
    reminder_offsets: List[int] = Field(default_factory=lambda: [0], description="Offsets in minutes before start_time")
    description: Optional[str] = Field(None, description="Detailed notes or instructions")


class ScheduleEventOutput(BaseModel):
    event_id: str
    title: str
    event_date: str
    start_time: Optional[str]
    reminders_created: int
    message: str


class ScheduleEventTool(BaseTool):
    name = "schedule_event"
    title = "Schedule Timetable Event"
    description = "Schedules an event, exam, assignment, or deadline in the user's local timetable with reminders."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = ScheduleEventInput
    output_schema = ScheduleEventOutput

    def __init__(self, timetable_mgr: TimetableManager) -> None:
        self.timetable = timetable_mgr

    async def execute(self, params: ScheduleEventInput, context: ToolContext) -> ScheduleEventOutput:
        cat = EventCategory(params.category.upper()) if params.category.upper() in EventCategory.__members__ else EventCategory.GENERAL_TASKS
        pri = EventPriority(params.priority.upper()) if params.priority.upper() in EventPriority.__members__ else EventPriority.MEDIUM
        rec = EventRecurrence(params.recurrence.upper()) if params.recurrence.upper() in EventRecurrence.__members__ else EventRecurrence.NONE

        event = await self.timetable.add_event_with_reminders(
            title=params.title,
            event_date=params.event_date,
            start_time=params.start_time,
            end_time=params.end_time,
            category=cat,
            priority=pri,
            recurrence=rec,
            reminder_offsets=params.reminder_offsets,
            description=params.description,
        )

        return ScheduleEventOutput(
            event_id=event.id,
            title=event.title,
            event_date=event.event_date,
            start_time=event.start_time,
            reminders_created=len(params.reminder_offsets),
            message=f"Scheduled '{event.title}' on {event.event_date} ({event.start_time or 'all-day'}).",
        )


# ---------------------------------------------------------------------------
# 2. List Events Tool (READ_ONLY)
# ---------------------------------------------------------------------------

class ListEventsInput(BaseModel):
    category: Optional[str] = Field(None, description="Optional category filter")
    date_from: Optional[str] = Field(None, description="Earliest event date YYYY-MM-DD")
    date_to: Optional[str] = Field(None, description="Latest event date YYYY-MM-DD")
    limit: int = Field(20, ge=1, le=100)


class ListedEvent(BaseModel):
    id: str
    title: str
    category: str
    priority: str
    event_date: str
    start_time: Optional[str]
    completion_status: str


class ListEventsOutput(BaseModel):
    events: List[ListedEvent]
    count: int


class ListEventsTool(BaseTool):
    name = "list_events"
    title = "List Timetable Events"
    description = "Queries the user's timetable for scheduled events, assignments, exams, and tasks."
    permission_tier = ToolPermissionTier.READ_ONLY
    input_schema = ListEventsInput
    output_schema = ListEventsOutput

    def __init__(self, timetable_mgr: TimetableManager) -> None:
        self.timetable = timetable_mgr

    async def execute(self, params: ListEventsInput, context: ToolContext) -> ListEventsOutput:
        cat = EventCategory(params.category.upper()) if params.category and params.category.upper() in EventCategory.__members__ else None
        items = await self.timetable.store.list_events(
            category=cat,
            date_from=params.date_from,
            date_to=params.date_to,
            limit=params.limit,
        )
        events_list = [
            ListedEvent(
                id=i.id,
                title=i.title,
                category=i.category.value,
                priority=i.priority.value,
                event_date=i.event_date,
                start_time=i.start_time,
                completion_status=i.completion_status.value,
            )
            for i in items
        ]
        return ListEventsOutput(events=events_list, count=len(events_list))


# ---------------------------------------------------------------------------
# 3. Query Agenda Tool (READ_ONLY)
# ---------------------------------------------------------------------------

class QueryAgendaInput(BaseModel):
    scope: str = Field("today", description="'today', 'tomorrow', or 'briefing'")


class QueryAgendaOutput(BaseModel):
    summary: str
    event_count: int
    overdue_count: int


class QueryAgendaTool(BaseTool):
    name = "query_agenda"
    title = "Query Daily Agenda & Deadlines"
    description = "Retrieves today's schedule, approaching deadlines, and urgent tasks."
    permission_tier = ToolPermissionTier.READ_ONLY
    input_schema = QueryAgendaInput
    output_schema = QueryAgendaOutput

    def __init__(self, briefing_gen: DailyBriefingGenerator, timetable_mgr: TimetableManager) -> None:
        self.briefing_gen = briefing_gen
        self.timetable = timetable_mgr

    async def execute(self, params: QueryAgendaInput, context: ToolContext) -> QueryAgendaOutput:
        briefing = await self.briefing_gen.generate_briefing()
        return QueryAgendaOutput(
            summary=briefing.summary_text,
            event_count=len(briefing.todays_events),
            overdue_count=len(briefing.overdue_tasks),
        )


# ---------------------------------------------------------------------------
# 4. Set Reminder Tool (LOW_RISK)
# ---------------------------------------------------------------------------

class SetReminderInput(BaseModel):
    title: str = Field(description="What to remind the user about")
    remind_at_iso: Optional[str] = Field(None, description="Exact local or UTC timestamp")
    relative_minutes: Optional[int] = Field(None, description="Minutes from now, e.g. 30")
    priority: str = Field("MEDIUM", description="LOW, MEDIUM, HIGH, URGENT")


class SetReminderOutput(BaseModel):
    reminder_id: str
    remind_at_local: str
    message: str


class SetReminderTool(BaseTool):
    name = "set_reminder"
    title = "Set Countdown or Specific Reminder"
    description = "Sets a standalone one-time reminder or timer."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = SetReminderInput
    output_schema = SetReminderOutput

    def __init__(self, timetable_mgr: TimetableManager) -> None:
        self.timetable = timetable_mgr

    async def execute(self, params: SetReminderInput, context: ToolContext) -> SetReminderOutput:
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        from zoro.schedule.models import ReminderCreate

        tz = ZoneInfo(self.timetable.default_timezone)
        now_local = datetime.now(tz)

        if params.relative_minutes is not None:
            remind_local = now_local + timedelta(minutes=params.relative_minutes)
        elif params.remind_at_iso:
            remind_local = datetime.fromisoformat(params.remind_at_iso)
            if remind_local.tzinfo is None:
                remind_local = remind_local.replace(tzinfo=tz)
        else:
            raise ValueError("Must provide either 'relative_minutes' or 'remind_at_iso'.")

        remind_utc = remind_local.astimezone(timezone.utc).isoformat()
        pri_str = params.priority.upper()
        pri = EventPriority(pri_str) if pri_str in EventPriority.__members__ else EventPriority.MEDIUM
        # Explicit user countdown timers (e.g. "remind me in 1 minute") take high operational priority
        if params.relative_minutes is not None and pri == EventPriority.MEDIUM:
            pri = EventPriority.HIGH

        rem = await self.timetable.store.create_reminder(
            ReminderCreate(
                event_id=None,
                remind_at_utc=remind_utc,
                remind_at_local=remind_local.strftime("%Y-%m-%d %H:%M:%S"),
                offset_minutes=0,
                title=params.title,
                message=f"Reminder: {params.title}",
                priority=pri,
            )
        )

        return SetReminderOutput(
            reminder_id=rem.id,
            remind_at_local=rem.remind_at_local,
            message=f"Reminder set for {rem.remind_at_local}: '{rem.title}'.",
        )


# ---------------------------------------------------------------------------
# 5. Start Focus Session Tool (LOW_RISK)
# ---------------------------------------------------------------------------

class StartFocusSessionInput(BaseModel):
    task_focus: str = Field(description="The primary objective or project to focus on")
    duration_minutes: int = Field(25, ge=1, le=480, description="Duration in minutes (e.g. 25, 45, 90)")


class StartFocusSessionOutput(BaseModel):
    session_id: str
    task_focus: str
    duration_minutes: int
    target_end_time: str
    message: str


class StartFocusSessionTool(BaseTool):
    name = "start_focus_session"
    title = "Start Deep Work Focus Session"
    description = "Initiates a dedicated focus session, muting non-essential notifications."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = StartFocusSessionInput
    output_schema = StartFocusSessionOutput

    def __init__(self, focus_mgr: FocusSessionManager) -> None:
        self.focus_mgr = focus_mgr

    async def execute(self, params: StartFocusSessionInput, context: ToolContext) -> StartFocusSessionOutput:
        session = await self.focus_mgr.start_session(
            task_focus=params.task_focus,
            duration_minutes=params.duration_minutes,
        )
        return StartFocusSessionOutput(
            session_id=session.id,
            task_focus=session.task_focus,
            duration_minutes=session.duration_minutes,
            target_end_time=session.target_end_time_utc,
            message=f"Focus session initiated: '{session.task_focus}' for {session.duration_minutes} minutes. Deep work engaged, Sir.",
        )


# ---------------------------------------------------------------------------
# 6. Configure Quiet Hours Tool (LOW_RISK)
# ---------------------------------------------------------------------------

class ConfigureQuietHoursInput(BaseModel):
    enabled: Optional[bool] = Field(None, description="Enable or disable quiet hours")
    start_time: Optional[str] = Field(None, description="Start time HH:MM, e.g. '23:00'")
    end_time: Optional[str] = Field(None, description="End time HH:MM, e.g. '07:00'")


class ConfigureQuietHoursOutput(BaseModel):
    enabled: bool
    start_time: str
    end_time: str
    message: str


class ConfigureQuietHoursTool(BaseTool):
    name = "configure_quiet_hours"
    title = "Configure Quiet Hours"
    description = "Updates quiet hours boundaries during which non-urgent notifications are suppressed."
    permission_tier = ToolPermissionTier.LOW_RISK
    input_schema = ConfigureQuietHoursInput
    output_schema = ConfigureQuietHoursOutput

    def __init__(self, store: ScheduleStore) -> None:
        self.store = store

    async def execute(self, params: ConfigureQuietHoursInput, context: ToolContext) -> ConfigureQuietHoursOutput:
        updates: Dict[str, Any] = {}
        if params.enabled is not None:
            updates["quiet_hours_enabled"] = params.enabled
        if params.start_time is not None:
            updates["quiet_hours_start"] = params.start_time
        if params.end_time is not None:
            updates["quiet_hours_end"] = params.end_time

        settings = await self.store.update_settings(updates)
        status_txt = "active" if settings.quiet_hours_enabled else "disabled"
        return ConfigureQuietHoursOutput(
            enabled=settings.quiet_hours_enabled,
            start_time=settings.quiet_hours_start,
            end_time=settings.quiet_hours_end,
            message=f"Quiet hours {status_txt}: {settings.quiet_hours_start} to {settings.quiet_hours_end}.",
        )
