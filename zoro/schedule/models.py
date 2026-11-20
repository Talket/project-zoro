"""Pydantic Domain Models & Enums for PROJECT ZORO Milestone 06.

Defines structured schemas for Events, Reminders, Focus Sessions,
Notifications, Settings, and Daily Briefings.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EventCategory(str, Enum):
    COLLEGE = "COLLEGE"
    EXAMS = "EXAMS"
    ASSIGNMENTS = "ASSIGNMENTS"
    PROJECTS = "PROJECTS"
    PERSONAL = "PERSONAL"
    MEETINGS = "MEETINGS"
    GENERAL_TASKS = "GENERAL_TASKS"


class EventPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class EventRecurrence(str, Enum):
    NONE = "NONE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    WEEKDAYS = "WEEKDAYS"
    MONTHLY = "MONTHLY"
    CUSTOM = "CUSTOM"


class EventCompletionStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    OVERDUE = "OVERDUE"


class EventSource(str, Enum):
    USER_COMMAND = "user_command"
    VOICE_COMMAND = "voice_command"
    EXTRACTED_MEMORY = "extracted_memory"
    PROACTIVE_ENGINE = "proactive_engine"
    UI_MANUAL = "ui_manual"


class ReminderStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    DELIVERED = "DELIVERED"
    DISMISSED = "DISMISSED"
    SNOOZED = "SNOOZED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class NotificationChannel(str, Enum):
    WINDOWS_TOAST = "WINDOWS_TOAST"
    SYSTEM_TRAY = "SYSTEM_TRAY"
    HUD_CONSOLE = "HUD_CONSOLE"
    VOICE_TTS = "VOICE_TTS"


class NotificationDeliveryStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FALLBACK = "FALLBACK"
    SUPPRESSED_QUIET_HOURS = "SUPPRESSED_QUIET_HOURS"
    FAILED = "FAILED"


class FocusSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Pydantic Schemas: Events
# ---------------------------------------------------------------------------

class EventBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    category: EventCategory = EventCategory.GENERAL_TASKS
    priority: EventPriority = EventPriority.MEDIUM
    event_date: str = Field(..., description="Local calendar date in YYYY-MM-DD format")
    start_time: Optional[str] = Field(None, description="Local military time in HH:MM format")
    end_time: Optional[str] = Field(None, description="Local military time in HH:MM format")
    timezone: str = "Asia/Kolkata"
    recurrence: EventRecurrence = EventRecurrence.NONE
    target_day_of_month: int = Field(0, description="Day of month for recurrence preservation (e.g. 31)")
    recurrence_interval_days: int = 0
    source: EventSource = EventSource.USER_COMMAND


class EventCreate(EventBase):
    reminder_offsets: List[int] = Field(default_factory=lambda: [0], description="Offsets in minutes before start_time")


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[EventCategory] = None
    priority: Optional[EventPriority] = None
    event_date: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    timezone: Optional[str] = None
    recurrence: Optional[EventRecurrence] = None
    target_day_of_month: Optional[int] = None
    recurrence_interval_days: Optional[int] = None
    completion_status: Optional[EventCompletionStatus] = None


class EventItem(EventBase):
    id: str
    completion_status: EventCompletionStatus = EventCompletionStatus.PENDING
    created_at: str
    updated_at: str
    is_deleted: bool = False


# ---------------------------------------------------------------------------
# Pydantic Schemas: Reminders
# ---------------------------------------------------------------------------

class ReminderBase(BaseModel):
    event_id: Optional[str] = None
    remind_at_utc: str
    remind_at_local: str
    offset_minutes: int = 0
    title: str
    message: str
    priority: EventPriority = EventPriority.MEDIUM


class ReminderCreate(ReminderBase):
    pass


class ReminderUpdate(BaseModel):
    remind_at_utc: Optional[str] = None
    remind_at_local: Optional[str] = None
    status: Optional[ReminderStatus] = None
    snooze_until_utc: Optional[str] = None
    delivered_at: Optional[str] = None
    dismissed_at: Optional[str] = None
    delivery_error: Optional[str] = None


class ReminderItem(ReminderBase):
    id: str
    status: ReminderStatus = ReminderStatus.PENDING
    claim_worker_id: Optional[str] = None
    claimed_at_utc: Optional[str] = None
    dispatch_attempts: int = 0
    last_attempt_at: Optional[str] = None
    delivered_at: Optional[str] = None
    dismissed_at: Optional[str] = None
    snooze_until_utc: Optional[str] = None
    delivery_error: Optional[str] = None
    created_at: str
    updated_at: str
    is_deleted: bool = False


# ---------------------------------------------------------------------------
# Pydantic Schemas: Focus Sessions
# ---------------------------------------------------------------------------

class FocusSessionCreate(BaseModel):
    task_focus: str
    duration_minutes: int = Field(25, ge=1, le=480)


class FocusSessionItem(BaseModel):
    id: str
    task_focus: str
    duration_minutes: int
    start_time_utc: str
    target_end_time_utc: str
    actual_end_time_utc: Optional[str] = None
    status: FocusSessionStatus = FocusSessionStatus.ACTIVE
    interruptions_count: int = 0
    notes: Optional[str] = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Pydantic Schemas: Notifications & History
# ---------------------------------------------------------------------------

class NotificationCreate(BaseModel):
    reminder_id: Optional[str] = None
    title: str
    body: str
    category: str = "GENERAL"
    channel: NotificationChannel = NotificationChannel.SYSTEM_TRAY
    delivery_status: NotificationDeliveryStatus = NotificationDeliveryStatus.SUCCESS
    dispatched_at_utc: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error_message: Optional[str] = None


class NotificationHistoryItem(BaseModel):
    id: str
    reminder_id: Optional[str] = None
    title: str
    body: str
    category: str
    channel: NotificationChannel
    delivery_status: NotificationDeliveryStatus
    dispatched_at_utc: str
    dismissed_at_utc: Optional[str] = None
    error_message: Optional[str] = None


# ---------------------------------------------------------------------------
# Pydantic Schemas: Settings & Briefing
# ---------------------------------------------------------------------------

class ScheduleSettings(BaseModel):
    system_timezone: str = "Asia/Kolkata"
    quiet_hours_enabled: bool = True
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "07:00"
    proactive_enabled: bool = True
    daily_briefing_enabled: bool = True
    daily_briefing_time: str = "08:30"
    last_daily_briefing_date: str = ""
    lead_time_exam_days: int = 3
    lead_time_assignment_days: int = 1


class DeadlineItem(BaseModel):
    event_id: str
    title: str
    category: EventCategory
    priority: EventPriority
    due_date: str
    due_time: Optional[str] = None
    hours_remaining: float
    is_overdue: bool
    urgency_score: float


class DailyBriefing(BaseModel):
    briefing_date: str
    generated_at: str
    greeting: str
    summary_text: str
    todays_events: List[EventItem] = Field(default_factory=list)
    upcoming_deadlines: List[DeadlineItem] = Field(default_factory=list)
    overdue_tasks: List[EventItem] = Field(default_factory=list)
    urgent_reminders: List[ReminderItem] = Field(default_factory=list)
