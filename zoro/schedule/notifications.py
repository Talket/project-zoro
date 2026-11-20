"""Multi-Tiered Notification Dispatcher & Quiet Hours Engine for PROJECT ZORO Milestone 06.

Provides native Windows Toast / System Tray integration, HUD activity console
fallback, quiet hours split-interval evaluation, and delivery history auditing.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any, Callable, Dict, Optional
from zoneinfo import ZoneInfo

from zoro.schedule.models import (
    EventPriority,
    NotificationChannel,
    NotificationCreate,
    NotificationDeliveryStatus,
    NotificationHistoryItem,
    ReminderItem,
    ScheduleSettings,
)
from zoro.schedule.store import ScheduleStore

logger = logging.getLogger(__name__)


class QuietHoursEvaluator:
    """Evaluates whether the current local time falls within configured quiet hours."""

    def __init__(
        self,
        enabled: bool = True,
        start_str: str = "23:00",
        end_str: str = "07:00",
        tz_name: str = "Asia/Kolkata",
    ) -> None:
        self.enabled = enabled
        self.start_str = start_str
        self.end_str = end_str
        self.tz_name = tz_name

    def should_suppress_notification(
        self, priority: EventPriority, dt: Optional[datetime] = None
    ) -> bool:
        if priority in (EventPriority.HIGH, EventPriority.URGENT):
            return False
        return self.is_in_quiet_hours(dt)

    def is_in_quiet_hours(
        self,
        current_time_or_dt: Any = None,
        start_str: Optional[str] = None,
        end_str: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> bool:
        """
        Split-interval evaluation supporting quiet hours crossing midnight.
        Works both as an instance method and as a class/static function.
        """
        # Instance call vs static call detection
        if isinstance(self, QuietHoursEvaluator):
            s_str = start_str if start_str is not None else self.start_str
            e_str = end_str if end_str is not None else self.end_str
            en = enabled if enabled is not None else self.enabled
            target = current_time_or_dt
        else:
            # Called as QuietHoursEvaluator.is_in_quiet_hours(current_time, start_str, end_str, enabled)
            target = self
            s_str = current_time_or_dt or "23:00"
            e_str = start_str or "07:00"
            en = end_str if end_str is not None else True

        if not en:
            return False

        if isinstance(target, datetime):
            current_t = target.time()
        elif isinstance(target, time):
            current_t = target
        elif target is None:
            try:
                tz = ZoneInfo(getattr(self, "tz_name", "Asia/Kolkata"))
            except Exception:
                tz = timezone.utc
            current_t = datetime.now(tz).time()
        else:
            current_t = target

        s_h, s_m = map(int, s_str.split(":"))
        e_h, e_m = map(int, e_str.split(":"))
        start_t = time(s_h, s_m)
        end_t = time(e_h, e_m)

        if start_t > end_t:
            # Crosses midnight
            return current_t >= start_t or current_t < end_t
        else:
            return start_t <= current_t < end_t


class NotificationDispatcher:
    """Dispatches notifications across native Windows Shell, System Tray, and HUD."""

    def __init__(
        self,
        store: ScheduleStore,
        event_bus_publisher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        tts_speaker: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.store = store
        self.publish_event = event_bus_publisher
        self.speak_tts = tts_speaker
        self._recently_dispatched: set[str] = set()

    async def dispatch_reminder(
        self,
        reminder: ReminderItem,
        settings: ScheduleSettings,
    ) -> NotificationHistoryItem:
        """
        Dispatch a reminder through the multi-tiered notification hierarchy:
        1. Check Quiet Hours (unless URGENT priority).
        2. Attempt Native Windows Toast / System Tray.
        3. Fallback to HUD In-App console.
        4. Optional Voice TTS announcement if enabled and audio idle.
        """
        # Deduplication check
        if reminder.id in self._recently_dispatched:
            logger.debug("Suppressing duplicate dispatch for reminder %s", reminder.id)
            return await self.store.record_notification(
                NotificationCreate(
                    reminder_id=reminder.id,
                    title=reminder.title,
                    body=reminder.message,
                    category="DUPLICATE_GUARD",
                    channel=NotificationChannel.HUD_CONSOLE,
                    delivery_status=NotificationDeliveryStatus.SUCCESS,
                )
            )

        tz = ZoneInfo(settings.system_timezone)
        now_local = datetime.now(tz)

        # 1. Quiet Hours check (HIGH and URGENT priorities bypass quiet hours)
        evaluator = QuietHoursEvaluator(
            enabled=settings.quiet_hours_enabled,
            start_str=settings.quiet_hours_start,
            end_str=settings.quiet_hours_end,
            tz_name=settings.system_timezone,
        )
        is_quiet = evaluator.should_suppress_notification(reminder.priority, now_local)

        if is_quiet:
            logger.info("Quiet hours active: deferring audible notification for '%s'", reminder.title)
            channel = NotificationChannel.HUD_CONSOLE
            status = NotificationDeliveryStatus.SUPPRESSED_QUIET_HOURS
            category = "QUIET_HOURS_DEFERRED"
        else:
            channel = NotificationChannel.SYSTEM_TRAY
            status = NotificationDeliveryStatus.SUCCESS
            category = reminder.priority.value

        err_msg = None

        # 2. Dispatch via Event Bus to UI / Windows System Tray (always emit so HUD logs alert)
        if self.publish_event:
            try:
                await self.publish_event(
                    "schedule.alert",
                    {
                        "reminder_id": reminder.id,
                        "title": reminder.title,
                        "message": reminder.message,
                        "priority": reminder.priority.value,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "is_silent": is_quiet,
                    },
                )
            except Exception as e:
                logger.warning("Event bus alert publish failed: %s. Falling back to HUD.", e)
                channel = NotificationChannel.HUD_CONSOLE
                status = NotificationDeliveryStatus.FALLBACK
                err_msg = str(e)

        # 3. Voice TTS Announcement (only when NOT silenced by quiet hours)
        if self.speak_tts and not is_quiet:
            try:
                spoken_text = f"Sir, reminder: {reminder.title}."
                self.speak_tts(spoken_text)
            except Exception as e:
                logger.debug("TTS voice alert failed: %s", e)

        # Track in deduplication cache
        self._recently_dispatched.add(reminder.id)
        if len(self._recently_dispatched) > 500:
            self._recently_dispatched.pop()

        # 4. Audit in Notification History
        return await self.store.record_notification(
            NotificationCreate(
                reminder_id=reminder.id,
                title=reminder.title,
                body=reminder.message,
                category=category,
                channel=channel,
                delivery_status=status,
                error_message=err_msg,
            )
        )
