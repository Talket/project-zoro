"""Background Persistent Scheduling Engine for PROJECT ZORO Milestone 06.

Executes atomic reminder polling (BEGIN IMMEDIATE), stale claim recovery,
sleep/hibernation catch-up sweeps, focus session ticking, and daily briefings.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from zoro.security.emergency import EmergencyManager
from zoro.schedule.briefing import DailyBriefingGenerator
from zoro.schedule.focus import FocusSessionManager
from zoro.schedule.models import (
    EventCompletionStatus,
    NotificationChannel,
    NotificationCreate,
    NotificationDeliveryStatus,
    ScheduleSettings,
)
from zoro.schedule.notifications import NotificationDispatcher
from zoro.schedule.parser import TemporalParser
from zoro.schedule.store import ScheduleStore
from zoro.schedule.timetable import TimetableManager

logger = logging.getLogger(__name__)


class SchedulerEngine:
    """The central local background scheduling engine for PROJECT ZORO."""

    def __init__(
        self,
        db_path: str,
        event_bus_publisher: Optional[Callable[[str, Dict[str, Any]], Any]] = None,
        tts_speaker: Optional[Callable[[str], Any]] = None,
        emergency_mgr: Optional[EmergencyManager] = None,
        instance_id: str = "engine-worker-1",
        poll_interval_sec: float = 2.0,
    ) -> None:
        self.db_path = db_path
        self.instance_id = instance_id
        self.poll_interval_sec = poll_interval_sec
        self.emergency_mgr = emergency_mgr or EmergencyManager()
        self.publish_event = event_bus_publisher

        # Subcomponents
        self.store = ScheduleStore(db_path=self.db_path)
        self.parser = TemporalParser(default_timezone="Asia/Kolkata")
        self.timetable = TimetableManager(store=self.store, parser=self.parser)
        self.notifications = NotificationDispatcher(
            store=self.store,
            event_bus_publisher=event_bus_publisher,
            tts_speaker=tts_speaker,
        )
        self.focus = FocusSessionManager(
            store=self.store,
            alert_notifier=self._on_focus_completed_alert,
        )
        self.briefing = DailyBriefingGenerator(timetable_mgr=self.timetable)

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._settings_cache: Optional[ScheduleSettings] = None

        # Clock-jump detection state
        self.clock_jump_threshold_sec: float = 5.0
        self._last_mono: float = time.monotonic()
        self._last_wall_utc: datetime = datetime.now(timezone.utc)

    def check_clock_jump(self, current_mono: float, current_wall_utc: datetime) -> bool:
        """
        Compare monotonic clock progression against UTC wall-clock progression.
        Returns True if a clock jump exceeding the threshold is detected.
        """
        elapsed_mono = current_mono - self._last_mono
        elapsed_wall = (current_wall_utc - self._last_wall_utc).total_seconds()
        is_jump = abs(elapsed_wall - elapsed_mono) > self.clock_jump_threshold_sec
        return is_jump

    async def initialize(self) -> None:
        """Run startup recovery sweeps and load initial configuration."""
        self._settings_cache = await self.store.get_settings()
        self.parser.default_timezone = self._settings_cache.system_timezone
        self.timetable.default_timezone = self._settings_cache.system_timezone

        # Run crash/sleep recovery sweep on startup
        await self.startup_recovery_sweep()
        logger.info("SchedulerEngine initialized (Timezone: %s)", self._settings_cache.system_timezone)

    async def start(self) -> None:
        """Start the background scheduler task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop(), name="zoro-scheduler-engine")
        logger.info("SchedulerEngine background loop started.")

    async def stop(self) -> None:
        """Gracefully stop the background scheduler loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("SchedulerEngine background loop stopped.")

    async def _on_focus_completed_alert(self, title: str, message: str) -> None:
        """Deliver focus session completion alert over the event bus."""
        if self.publish_event:
            await self.publish_event(
                "schedule.alert",
                {
                    "title": title,
                    "message": message,
                    "priority": "HIGH",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

    # =========================================================================
    # Crash & Sleep Recovery
    # =========================================================================

    async def startup_recovery_sweep(self) -> None:
        """Scan for reminders missed while the machine was asleep or offline."""
        now_utc = datetime.now(timezone.utc).isoformat()
        recent_missed, expired_missed = await self.store.recover_missed_reminders(now_utc=now_utc)

        if not recent_missed:
            return

        # Consolidated single batch alert if 1 or more reminders were missed
        if len(recent_missed) == 1:
            r = recent_missed[0]
            title = "PROJECT ZORO // Missed Reminder"
            msg = f"Missed while offline: '{r.title}' (scheduled for {r.remind_at_local})."
        else:
            titles_summary = ", ".join([f"'{r.title}'" for r in recent_missed[:3]])
            if len(recent_missed) > 3:
                titles_summary += f" and {len(recent_missed) - 3} more"
            title = f"PROJECT ZORO // {len(recent_missed)} Missed Reminders"
            msg = f"Items became due while the system was offline: {titles_summary}."

        # Mark all recent as delivered with recovery note
        for r in recent_missed:
            await self.store.mark_reminder_delivered(r.id, now_utc)

        # Record single consolidated notification in history and dispatch
        await self.store.record_notification(
            NotificationCreate(
                title=title,
                body=msg,
                category="MISSED_RECOVERY",
                channel=NotificationChannel.SYSTEM_TRAY,
                delivery_status=NotificationDeliveryStatus.SUCCESS,
            )
        )

        if self.publish_event:
            try:
                await self.publish_event(
                    "schedule.alert",
                    {
                        "title": title,
                        "message": msg,
                        "priority": "HIGH",
                        "timestamp": now_utc,
                    },
                )
            except Exception as e:
                logger.debug("Failed to dispatch catch-up alert: %s", e)

    # =========================================================================
    # Main Polling Loop
    # =========================================================================

    async def _scheduler_loop(self) -> None:
        """Periodic background polling loop with clock-jump detection and monotonic interval control."""
        import datetime as dt_mod

        self._last_mono = time.monotonic()
        self._last_wall_utc = datetime.now(timezone.utc)

        while self._running:
            loop_start_mono = time.monotonic()

            # 1. Emergency safety check
            is_halted, _ = self.emergency_mgr.is_halted()
            if is_halted:
                logger.warning("Emergency halt active; scheduler engine pausing loop.")
                break

            try:
                now_utc = datetime.now(timezone.utc)
                now_utc_iso = now_utc.isoformat()

                # Clock-jump detection: manual time change or resume from sleep
                if self.check_clock_jump(loop_start_mono, now_utc):
                    logger.warning(
                        "System clock jump detected! Executing fresh due-reminder sweep immediately."
                    )
                    await self.startup_recovery_sweep()

                self._last_mono = loop_start_mono
                self._last_wall_utc = now_utc

                # 60s stale cutoff for abandoned claims
                stale_cutoff = (now_utc - dt_mod.timedelta(seconds=60)).isoformat()

                # Refresh settings every 30 seconds
                settings = await self.store.get_settings()
                self._settings_cache = settings

                # 2. Atomic claim of due reminders (BEGIN IMMEDIATE)
                claimed = await self.store.claim_due_reminders(
                    worker_id=self.instance_id,
                    now_utc=now_utc_iso,
                    stale_cutoff_utc=stale_cutoff,
                    limit=5,
                )

                # 3. Dispatch each claimed reminder
                for rem in claimed:
                    try:
                        delivery_record = await self.notifications.dispatch_reminder(rem, settings)
                        if delivery_record.delivery_status in (
                            NotificationDeliveryStatus.SUCCESS,
                            NotificationDeliveryStatus.FALLBACK,
                            NotificationDeliveryStatus.SUPPRESSED_QUIET_HOURS,
                        ):
                            await self.store.mark_reminder_delivered(rem.id, now_utc_iso)
                        else:
                            if rem.dispatch_attempts >= 3:
                                await self.store.mark_reminder_failed(rem.id, delivery_record.error_message or "Max retries exceeded")
                    except Exception as ex:
                        logger.error("Error dispatching reminder %s: %s", rem.id, ex)
                        if rem.dispatch_attempts >= 3:
                            await self.store.mark_reminder_failed(rem.id, str(ex))

                # 4. Check active focus session completion
                await self.focus.check_session_tick()

                # 5. Check daily morning briefing
                await self._check_daily_briefing(settings)

            except Exception as e:
                logger.error("Unexpected error in scheduler loop: %s", e, exc_info=True)

            # Monotonic elapsed sleep compensation
            elapsed = time.monotonic() - loop_start_mono
            sleep_time = max(0.1, self.poll_interval_sec - elapsed)
            await asyncio.sleep(sleep_time)

    async def _check_daily_briefing(self, settings: ScheduleSettings) -> None:
        """Check if today's morning briefing should be triggered."""
        if not settings.daily_briefing_enabled:
            return

        tz = ZoneInfo(settings.system_timezone)
        now_local = datetime.now(tz)
        today_date_str = now_local.strftime("%Y-%m-%d")

        if settings.last_daily_briefing_date == today_date_str:
            return  # Already delivered today

        # Parse target briefing time (e.g. "08:30")
        b_h, b_m = map(int, settings.daily_briefing_time.split(":"))
        if now_local.hour > b_h or (now_local.hour == b_h and now_local.minute >= b_m):
            logger.info("Triggering Daily Briefing for %s...", today_date_str)
            briefing = await self.briefing.generate_briefing(settings)

            # Record in notification history and publish
            title = f"PROJECT ZORO // Daily Briefing ({today_date_str})"
            body = briefing.summary_text

            await self.store.record_notification(
                NotificationCreate(
                    title=title,
                    body=body,
                    category="DAILY_BRIEFING",
                    channel=NotificationChannel.SYSTEM_TRAY,
                    delivery_status=NotificationDeliveryStatus.SUCCESS,
                )
            )

            if self.publish_event:
                await self.publish_event(
                    "schedule.briefing",
                    {
                        "briefing_date": today_date_str,
                        "title": title,
                        "summary": body,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )

            # Mark as delivered for today
            await self.store.update_settings({"last_daily_briefing_date": today_date_str})
