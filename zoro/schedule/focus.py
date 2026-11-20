"""Focus Mode & Deep Work Manager for PROJECT ZORO Milestone 06.

Tracks focus sessions, duration countdowns, completion notifications,
and suppression of non-critical interruptions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from zoro.schedule.models import (
    FocusSessionCreate,
    FocusSessionItem,
    FocusSessionStatus,
    NotificationChannel,
    NotificationCreate,
    NotificationDeliveryStatus,
)
from zoro.schedule.store import ScheduleStore

logger = logging.getLogger(__name__)


class FocusSessionManager:
    """Manages active focus sessions and deep work timers."""

    def __init__(
        self,
        store: ScheduleStore,
        alert_notifier: Optional[Callable[[str, str], Any]] = None,
    ) -> None:
        self.store = store
        self.notifier = alert_notifier

    async def start_session(
        self,
        duration_minutes: int = 25,
        goal: Optional[str] = None,
        task_focus: Optional[str] = None,
    ) -> FocusSessionItem:
        """Begin a new focus session."""
        focus_title = goal or task_focus or "Deep Work"
        session = await self.store.create_focus_session(
            FocusSessionCreate(task_focus=focus_title, duration_minutes=duration_minutes)
        )
        logger.info("Focus session '%s' active for %d minutes.", focus_title, duration_minutes)
        return session

    async def is_focus_active(self) -> bool:
        """Check whether a focus session is currently running."""
        sess = await self.get_active_session()
        return sess is not None

    async def stop_session(self) -> Optional[FocusSessionItem]:
        """Cancel or complete the active focus session."""
        return await self.stop_session_early()

    async def get_active_session(self) -> Optional[FocusSessionItem]:
        """Fetch the currently running focus session, if any."""
        return await self.store.get_active_focus_session()

    async def get_remaining_minutes(self) -> Optional[float]:
        """Calculate remaining minutes in the active focus session."""
        session = await self.get_active_session()
        if not session:
            return None

        now = datetime.now(timezone.utc)
        target_end = datetime.fromisoformat(session.target_end_time_utc)
        remaining = (target_end - now).total_seconds() / 60.0
        return max(0.0, round(remaining, 1))

    async def check_session_tick(self) -> Optional[FocusSessionItem]:
        """Periodic tick check: if session time has expired, complete it and notify user."""
        session = await self.get_active_session()
        if not session:
            return None

        now = datetime.now(timezone.utc)
        target_end = datetime.fromisoformat(session.target_end_time_utc)

        if now >= target_end:
            completed = await self.store.complete_focus_session(session.id, now.isoformat())
            logger.info("Focus session '%s' completed successfully.", session.task_focus)

            # Record in notification history and notify
            title = "PROJECT ZORO // Focus Session Completed"
            msg = f"Deep work session '{session.task_focus}' ({session.duration_minutes} mins) has concluded. Excellent work, Sir."

            await self.store.record_notification(
                NotificationCreate(
                    title=title,
                    body=msg,
                    category="FOCUS_SESSION",
                    channel=NotificationChannel.SYSTEM_TRAY,
                    delivery_status=NotificationDeliveryStatus.SUCCESS,
                )
            )

            if self.notifier:
                try:
                    await self.notifier(title, msg)
                except Exception as e:
                    logger.debug("Focus completion notification dispatch failed: %s", e)

            return completed

        return session

    async def stop_session_early(self) -> Optional[FocusSessionItem]:
        """Cancel the active focus session."""
        session = await self.get_active_session()
        if not session:
            return None
        return await self.store.cancel_focus_session(session.id)
