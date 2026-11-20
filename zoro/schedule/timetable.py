"""Timetable & Deadline Management Subsystem for PROJECT ZORO Milestone 06.

Handles event organization, deadline urgency calculations, scheduling conflict
detection, recurring event advancement, and countdown tracking.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from zoro.schedule.models import (
    DeadlineItem,
    EventCategory,
    EventCompletionStatus,
    EventCreate,
    EventItem,
    EventPriority,
    EventRecurrence,
    EventSource,
    EventUpdate,
    ReminderCreate,
)
from zoro.schedule.parser import TemporalParser
from zoro.schedule.store import ScheduleStore

logger = logging.getLogger(__name__)


class TimetableManager:
    """Coordinates timetable events, deadline intelligence, and conflict resolution."""

    PRIORITY_WEIGHTS = {
        EventPriority.LOW: 1.0,
        EventPriority.MEDIUM: 2.0,
        EventPriority.HIGH: 4.0,
        EventPriority.URGENT: 8.0,
    }

    def __init__(
        self,
        store: ScheduleStore,
        parser: Optional[TemporalParser] = None,
        default_timezone: str = "Asia/Kolkata",
    ) -> None:
        self.store = store
        self.default_timezone = default_timezone
        self.parser = parser or TemporalParser(default_timezone=default_timezone)

    async def add_event_with_reminders(
        self,
        title: str,
        event_date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        category: EventCategory = EventCategory.GENERAL_TASKS,
        priority: EventPriority = EventPriority.MEDIUM,
        recurrence: EventRecurrence = EventRecurrence.NONE,
        target_day_of_month: int = 0,
        reminder_offsets: Optional[List[int]] = None,
        source: EventSource = EventSource.USER_COMMAND,
        description: Optional[str] = None,
    ) -> EventItem:
        """Create an event and generate all associated reminder rows atomically."""
        offsets = reminder_offsets if reminder_offsets is not None else [0]

        # Extract target day of month if recurring monthly
        if recurrence == EventRecurrence.MONTHLY and target_day_of_month == 0:
            target_day_of_month = int(event_date.split("-")[2])

        event_create = EventCreate(
            title=title,
            description=description,
            category=category,
            priority=priority,
            event_date=event_date,
            start_time=start_time,
            end_time=end_time,
            timezone=self.default_timezone,
            recurrence=recurrence,
            target_day_of_month=target_day_of_month,
            reminder_offsets=offsets,
            source=source,
        )

        event = await self.store.create_event(event_create)

        # Generate attached reminders
        for offset in offsets:
            remind_utc, remind_local = self.parser.calculate_remind_at_utc(
                event_date_str=event.event_date,
                start_time_str=event.start_time,
                offset_minutes=offset,
                event_timezone=event.timezone,
            )
            rem_title = f"{event.title}" if offset == 0 else f"{event.title} (in {offset} mins)"
            rem_msg = f"Upcoming {event.category.value.lower()}: '{event.title}' scheduled for {event.event_date} at {event.start_time or 'all-day'}."
            await self.store.create_reminder(
                ReminderCreate(
                    event_id=event.id,
                    remind_at_utc=remind_utc,
                    remind_at_local=remind_local,
                    offset_minutes=offset,
                    title=rem_title,
                    message=rem_msg,
                    priority=event.priority,
                )
            )

        return event

    async def get_todays_agenda(self) -> List[EventItem]:
        """Fetch all non-completed events scheduled for today."""
        today_str = self.parser.now_local().strftime("%Y-%m-%d")
        return await self.store.list_events(date_from=today_str, date_to=today_str)

    async def get_upcoming_deadlines(self, horizon_days: int = 7) -> List[DeadlineItem]:
        """
        Calculate remaining time, overdue state, and urgency ranking for deadlines.
        """
        now = self.parser.now_local()
        today_str = now.strftime("%Y-%m-%d")
        future_str = (now.date() + timedelta(days=horizon_days)).strftime("%Y-%m-%d")

        events = await self.store.list_events(
            date_from=today_str,
            date_to=future_str,
            completion_status=EventCompletionStatus.PENDING,
        )

        deadlines: List[DeadlineItem] = []
        tz = self.parser.get_tz()

        for ev in events:
            # Parse due datetime
            d_parts = list(map(int, ev.event_date.split("-")))
            if ev.end_time:
                t_parts = list(map(int, ev.end_time.split(":")))
            elif ev.start_time:
                t_parts = list(map(int, ev.start_time.split(":")))
            else:
                t_parts = [23, 59]

            due_dt = datetime(d_parts[0], d_parts[1], d_parts[2], t_parts[0], t_parts[1], tzinfo=tz)
            remaining_seconds = (due_dt - now).total_seconds()
            hours_remaining = remaining_seconds / 3600.0
            is_overdue = remaining_seconds < 0

            # Calculate urgency score
            p_weight = self.PRIORITY_WEIGHTS.get(ev.priority, 2.0)
            urgency = p_weight * (1.0 / max(0.1, hours_remaining if not is_overdue else 0.05))

            deadlines.append(
                DeadlineItem(
                    event_id=ev.id,
                    title=ev.title,
                    category=ev.category,
                    priority=ev.priority,
                    due_date=ev.event_date,
                    due_time=ev.end_time or ev.start_time,
                    hours_remaining=round(hours_remaining, 1),
                    is_overdue=is_overdue,
                    urgency_score=round(urgency, 4),
                )
            )

        # Sort by urgency descending (highest priority & closest deadline first)
        deadlines.sort(key=lambda d: d.urgency_score, reverse=True)
        return deadlines

    async def get_overdue_tasks(self) -> List[EventItem]:
        """Fetch all incomplete events from past dates."""
        today_str = self.parser.now_local().strftime("%Y-%m-%d")
        past_events = await self.store.list_events(date_to=today_str, completion_status=EventCompletionStatus.PENDING)
        # Exclude today's events that haven't ended yet
        now = self.parser.now_local()
        overdue: List[EventItem] = []
        for ev in past_events:
            if ev.event_date < today_str:
                overdue.append(ev)
            elif ev.event_date == today_str and ev.end_time:
                t_parts = list(map(int, ev.end_time.split(":")))
                if now.time() > datetime(now.year, now.month, now.day, t_parts[0], t_parts[1]).time():
                    overdue.append(ev)
        return overdue

    async def detect_scheduling_conflicts(
        self,
        event_date: str,
        start_time: str,
        end_time: str,
        exclude_event_id: Optional[str] = None,
    ) -> List[EventItem]:
        """Detect any existing events overlapping with the requested time interval."""
        if not start_time or not end_time:
            return []

        day_events = await self.store.list_events(date_from=event_date, date_to=event_date)
        conflicts: List[EventItem] = []

        new_start = start_time
        new_end = end_time

        for ev in day_events:
            if exclude_event_id and ev.id == exclude_event_id:
                continue
            if not ev.start_time or not ev.end_time:
                continue
            # Overlap condition: startA < endB and endA > startB
            if new_start < ev.end_time and new_end > ev.start_time:
                conflicts.append(ev)

        return conflicts

    async def advance_recurring_event(self, event_id: str) -> Optional[EventItem]:
        """Calculate and schedule the next occurrence for a recurring event."""
        event = await self.store.get_event(event_id)
        if not event or event.recurrence == EventRecurrence.NONE:
            return None

        curr_date = date.fromisoformat(event.event_date)

        if event.recurrence == EventRecurrence.DAILY:
            next_date = curr_date + timedelta(days=1)
        elif event.recurrence == EventRecurrence.WEEKDAYS:
            next_date = curr_date + timedelta(days=1)
            while next_date.weekday() >= 5:  # Skip Saturday (5) and Sunday (6)
                next_date += timedelta(days=1)
        elif event.recurrence == EventRecurrence.WEEKLY:
            next_date = curr_date + timedelta(days=7)
        elif event.recurrence == EventRecurrence.MONTHLY:
            target_day = event.target_day_of_month or curr_date.day
            next_date = TemporalParser.calculate_next_monthly_occurrence(curr_date, target_day)
        elif event.recurrence == EventRecurrence.CUSTOM and event.recurrence_interval_days > 0:
            next_date = curr_date + timedelta(days=event.recurrence_interval_days)
        else:
            return None

        next_date_str = next_date.strftime("%Y-%m-%d")
        logger.info("Advancing recurring event '%s' from %s to %s", event.title, event.event_date, next_date_str)

        # Create next occurrence
        return await self.add_event_with_reminders(
            title=event.title,
            event_date=next_date_str,
            start_time=event.start_time,
            end_time=event.end_time,
            category=event.category,
            priority=event.priority,
            recurrence=event.recurrence,
            target_day_of_month=event.target_day_of_month,
            source=EventSource.PROACTIVE_ENGINE,
            description=event.description,
        )
