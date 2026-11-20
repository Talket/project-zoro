"""Persistent SQLite Storage for PROJECT ZORO Milestone 06.

Implements crash-safe, atomic reminder claiming (BEGIN IMMEDIATE),
events/reminders decoupled storage, focus sessions, and delivery history.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import aiosqlite

from zoro.schedule.models import (
    EventCategory,
    EventCompletionStatus,
    EventCreate,
    EventItem,
    EventPriority,
    EventRecurrence,
    EventSource,
    EventUpdate,
    FocusSessionCreate,
    FocusSessionItem,
    FocusSessionStatus,
    NotificationChannel,
    NotificationCreate,
    NotificationDeliveryStatus,
    NotificationHistoryItem,
    ReminderCreate,
    ReminderItem,
    ReminderStatus,
    ReminderUpdate,
    ScheduleSettings,
)

logger = logging.getLogger(__name__)


class ScheduleStore:
    """Manages persistent SQLite operations for timetable, reminders, and proactive settings."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    # =========================================================================
    # 1. EVENTS MANAGEMENT
    # =========================================================================

    async def create_event(self, item: EventCreate) -> EventItem:
        """Create a new timetable event and generate attached reminders transactionally."""
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        query_event = """
        INSERT INTO events (
            id, title, description, category, priority, event_date,
            start_time, end_time, timezone, recurrence, target_day_of_month,
            recurrence_interval_days, completion_status, source,
            created_at, updated_at, is_deleted
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?, ?, 0);
        """
        params_event = (
            event_id,
            item.title,
            item.description,
            item.category.value,
            item.priority.value,
            item.event_date,
            item.start_time,
            item.end_time,
            item.timezone,
            item.recurrence.value,
            item.target_day_of_month,
            item.recurrence_interval_days,
            item.source.value,
            now,
            now,
        )

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON;")
            await conn.execute(query_event, params_event)
            await conn.commit()

        logger.info("Created event '%s' (ID: %s, Date: %s)", item.title, event_id, item.event_date)
        return EventItem(
            id=event_id,
            title=item.title,
            description=item.description,
            category=item.category,
            priority=item.priority,
            event_date=item.event_date,
            start_time=item.start_time,
            end_time=item.end_time,
            timezone=item.timezone,
            recurrence=item.recurrence,
            target_day_of_month=item.target_day_of_month,
            recurrence_interval_days=item.recurrence_interval_days,
            completion_status=EventCompletionStatus.PENDING,
            source=item.source,
            created_at=now,
            updated_at=now,
            is_deleted=False,
        )

    async def get_event(self, event_id: str) -> Optional[EventItem]:
        """Fetch a single event by ID."""
        query = "SELECT * FROM events WHERE id = ? AND is_deleted = 0;"
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, (event_id,))
            row = await cursor.fetchone()
            if row:
                return self._row_to_event(row)
        return None

    async def update_event(self, event_id: str, update: EventUpdate) -> Optional[EventItem]:
        """Update event fields and cascade changes to reminders if needed."""
        existing = await self.get_event(event_id)
        if not existing:
            return None

        clauses = []
        params = []
        now = datetime.now(timezone.utc).isoformat()

        if update.title is not None:
            clauses.append("title = ?")
            params.append(update.title)
        if update.description is not None:
            clauses.append("description = ?")
            params.append(update.description)
        if update.category is not None:
            clauses.append("category = ?")
            params.append(update.category.value)
        if update.priority is not None:
            clauses.append("priority = ?")
            params.append(update.priority.value)
        if update.event_date is not None:
            clauses.append("event_date = ?")
            params.append(update.event_date)
        if update.start_time is not None:
            clauses.append("start_time = ?")
            params.append(update.start_time)
        if update.end_time is not None:
            clauses.append("end_time = ?")
            params.append(update.end_time)
        if update.timezone is not None:
            clauses.append("timezone = ?")
            params.append(update.timezone)
        if update.recurrence is not None:
            clauses.append("recurrence = ?")
            params.append(update.recurrence.value)
        if update.target_day_of_month is not None:
            clauses.append("target_day_of_month = ?")
            params.append(update.target_day_of_month)
        if update.recurrence_interval_days is not None:
            clauses.append("recurrence_interval_days = ?")
            params.append(update.recurrence_interval_days)
        if update.completion_status is not None:
            clauses.append("completion_status = ?")
            params.append(update.completion_status.value)

        if not clauses:
            return existing

        clauses.append("updated_at = ?")
        params.append(now)
        params.append(event_id)

        query = f"UPDATE events SET {', '.join(clauses)} WHERE id = ? AND is_deleted = 0;"
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON;")
            await conn.execute(query, tuple(params))

            # Cascade cancellation/completion to reminders if event is completed or cancelled
            if update.completion_status in (EventCompletionStatus.COMPLETED, EventCompletionStatus.CANCELLED):
                await conn.execute(
                    "UPDATE reminders SET status = 'CANCELLED', updated_at = ? WHERE event_id = ? AND status IN ('PENDING', 'SNOOZED', 'CLAIMED');",
                    (now, event_id),
                )
            await conn.commit()

        logger.info("Updated event %s (Status: %s)", event_id, update.completion_status)
        return await self.get_event(event_id)

    async def delete_event(self, event_id: str, hard_delete: bool = False) -> bool:
        """Soft-delete or purge an event and cascade to reminders."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON;")
            if hard_delete:
                cursor = await conn.execute("DELETE FROM events WHERE id = ?;", (event_id,))
            else:
                cursor = await conn.execute(
                    "UPDATE events SET is_deleted = 1, updated_at = ? WHERE id = ? AND is_deleted = 0;",
                    (now, event_id),
                )
                await conn.execute(
                    "UPDATE reminders SET is_deleted = 1, status = 'CANCELLED', updated_at = ? WHERE event_id = ?;",
                    (now, event_id),
                )
            await conn.commit()
            return cursor.rowcount > 0

    async def list_events(
        self,
        category: Optional[EventCategory] = None,
        priority: Optional[EventPriority] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        completion_status: Optional[EventCompletionStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[EventItem]:
        """Query events matching filters."""
        clauses = ["is_deleted = 0"]
        params: List[Any] = []

        if category:
            clauses.append("category = ?")
            params.append(category.value)
        if priority:
            clauses.append("priority = ?")
            params.append(priority.value)
        if date_from:
            clauses.append("event_date >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("event_date <= ?")
            params.append(date_to)
        if completion_status:
            clauses.append("completion_status = ?")
            params.append(completion_status.value)

        query = f"""
        SELECT * FROM events
        WHERE {' AND '.join(clauses)}
        ORDER BY event_date ASC, start_time ASC
        LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, tuple(params))
            rows = await cursor.fetchall()
            return [self._row_to_event(r) for r in rows]

    # =========================================================================
    # 2. REMINDERS MANAGEMENT & ATOMIC CLAIMING (BEGIN IMMEDIATE)
    # =========================================================================

    async def create_reminder(self, item: ReminderCreate) -> ReminderItem:
        """Create a new reminder record."""
        reminder_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        query = """
        INSERT INTO reminders (
            id, event_id, remind_at_utc, remind_at_local, offset_minutes,
            title, message, priority, status, dispatch_attempts,
            created_at, updated_at, is_deleted
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', 0, ?, ?, 0);
        """
        params = (
            reminder_id,
            item.event_id,
            item.remind_at_utc,
            item.remind_at_local,
            item.offset_minutes,
            item.title,
            item.message,
            item.priority.value,
            now,
            now,
        )

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON;")
            await conn.execute(query, params)
            await conn.commit()

        logger.info("Created reminder '%s' (ID: %s, at: %s)", item.title, reminder_id, item.remind_at_local)
        return ReminderItem(
            id=reminder_id,
            event_id=item.event_id,
            remind_at_utc=item.remind_at_utc,
            remind_at_local=item.remind_at_local,
            offset_minutes=item.offset_minutes,
            title=item.title,
            message=item.message,
            priority=item.priority,
            status=ReminderStatus.PENDING,
            dispatch_attempts=0,
            created_at=now,
            updated_at=now,
            is_deleted=False,
        )

    async def get_reminder(self, reminder_id: str) -> Optional[ReminderItem]:
        """Fetch a single reminder by ID."""
        query = "SELECT * FROM reminders WHERE id = ? AND is_deleted = 0;"
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, (reminder_id,))
            row = await cursor.fetchone()
            if row:
                return self._row_to_reminder(row)
        return None

    async def list_reminders_for_event(self, event_id: str) -> List[ReminderItem]:
        """Query all active reminders associated with an event."""
        query = "SELECT * FROM reminders WHERE event_id = ? AND is_deleted = 0 ORDER BY remind_at_utc ASC;"
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, (event_id,))
            rows = await cursor.fetchall()
            return [self._row_to_reminder(r) for r in rows]

    async def get_reminders_for_event(self, event_id: str) -> List[ReminderItem]:
        """Alias for list_reminders_for_event."""
        return await self.list_reminders_for_event(event_id)

    async def claim_due_reminders(
        self,
        worker_id: str,
        now_utc: str,
        stale_cutoff_utc: str,
        limit: int = 10,
    ) -> List[ReminderItem]:
        """
        Atomically claim due reminders using BEGIN IMMEDIATE locking.
        
        Guarantees that:
        1. Only one worker can acquire exclusive claim on a candidate row.
        2. Verified via cursor.rowcount == 1 for every item.
        3. Recovers stale claims abandoned by crashed workers.
        """
        claimed_items: List[ReminderItem] = []

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            # 1. Acquire immediate lock to prevent concurrent writers from reading the same rows
            await conn.execute("BEGIN IMMEDIATE;")

            # 2. Select eligible candidates (PENDING or SNOOZED due, or stale CLAIMED)
            select_sql = """
            SELECT id FROM reminders
            WHERE is_deleted = 0
              AND (
                (status = 'PENDING' AND remind_at_utc <= ?)
                OR (status = 'SNOOZED' AND snooze_until_utc <= ?)
                OR (status = 'CLAIMED' AND claimed_at_utc <= ?)
              )
            ORDER BY priority DESC, remind_at_utc ASC
            LIMIT ?;
            """
            cursor = await conn.execute(select_sql, (now_utc, now_utc, stale_cutoff_utc, limit))
            candidate_rows = await cursor.fetchall()

            for row in candidate_rows:
                r_id = row["id"]
                # 3. Atomically transition row to CLAIMED
                update_sql = """
                UPDATE reminders
                SET status = 'CLAIMED',
                    claim_worker_id = ?,
                    claimed_at_utc = ?,
                    dispatch_attempts = dispatch_attempts + 1,
                    last_attempt_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND (
                    status IN ('PENDING', 'SNOOZED')
                    OR (status = 'CLAIMED' AND claimed_at_utc <= ?)
                  )
                  AND is_deleted = 0;
                """
                up_cursor = await conn.execute(
                    update_sql,
                    (worker_id, now_utc, now_utc, now_utc, r_id, stale_cutoff_utc),
                )
                if up_cursor.rowcount == 1:
                    # Verified exclusive claim
                    get_cursor = await conn.execute("SELECT * FROM reminders WHERE id = ?;", (r_id,))
                    updated_row = await get_cursor.fetchone()
                    if updated_row:
                        claimed_items.append(self._row_to_reminder(updated_row))
                else:
                    logger.debug("Worker %s lost race to claim reminder %s", worker_id, r_id)

            await conn.commit()

        if claimed_items:
            logger.info("Worker %s atomically claimed %d due reminders.", worker_id, len(claimed_items))
        return claimed_items

    async def mark_reminder_delivered(self, reminder_id: str, delivered_at_utc: str) -> bool:
        """Mark a claimed reminder as successfully delivered to the OS / user."""
        query = """
        UPDATE reminders
        SET status = 'DELIVERED',
            delivered_at = ?,
            updated_at = ?
        WHERE id = ? AND is_deleted = 0;
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(query, (delivered_at_utc, delivered_at_utc, reminder_id))
            await conn.commit()
            return cursor.rowcount > 0

    async def mark_reminder_failed(self, reminder_id: str, error: str) -> bool:
        """Mark a reminder as failed after exceeding retry attempts."""
        now = datetime.now(timezone.utc).isoformat()
        query = """
        UPDATE reminders
        SET status = 'FAILED',
            delivery_error = ?,
            updated_at = ?
        WHERE id = ?;
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(query, (error, now, reminder_id))
            await conn.commit()
            return cursor.rowcount > 0

    async def snooze_reminder(self, reminder_id: str, snooze_until_utc: str) -> bool:
        """Snooze a reminder until the specified UTC timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        query = """
        UPDATE reminders
        SET status = 'SNOOZED',
            snooze_until_utc = ?,
            updated_at = ?
        WHERE id = ? AND is_deleted = 0;
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(query, (snooze_until_utc, now, reminder_id))
            await conn.commit()
            return cursor.rowcount > 0

    async def dismiss_reminder(self, reminder_id: str, dismissed_at_utc: str) -> bool:
        """Acknowledge and dismiss a delivered reminder."""
        query = """
        UPDATE reminders
        SET status = 'DISMISSED',
            dismissed_at = ?,
            updated_at = ?
        WHERE id = ? AND is_deleted = 0;
        """
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(query, (dismissed_at_utc, dismissed_at_utc, reminder_id))
            await conn.commit()
            return cursor.rowcount > 0

    async def recover_missed_reminders(
        self,
        now_utc: str,
        threshold_hours: float = 24.0,
        max_missed_age_hours: Optional[float] = None,
    ) -> Tuple[List[ReminderItem], List[ReminderItem]]:
        """
        Identify reminders that became due while the machine was asleep or offline.
        Returns:
            (recent_missed, expired_missed)
        """
        cutoff_hours = max_missed_age_hours if max_missed_age_hours is not None else threshold_hours
        query = """
        SELECT * FROM reminders
        WHERE is_deleted = 0
          AND status IN ('PENDING', 'SNOOZED')
          AND remind_at_utc < ?
        ORDER BY remind_at_utc ASC;
        """
        recent: List[ReminderItem] = []
        expired: List[ReminderItem] = []

        now_dt = datetime.fromisoformat(now_utc)

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, (now_utc,))
            rows = await cursor.fetchall()

            for row in rows:
                item = self._row_to_reminder(row)
                item_dt = datetime.fromisoformat(item.remind_at_utc)
                diff_hours = (now_dt - item_dt).total_seconds() / 3600.0

                if diff_hours <= cutoff_hours:
                    recent.append(item)
                else:
                    expired.append(item)
                    # Mark expired as MISSED in database
                    await conn.execute(
                        "UPDATE reminders SET status = 'MISSED', delivery_error = 'EXPIRED_WHILE_OFFLINE', updated_at = ? WHERE id = ?;",
                        (now_utc, item.id),
                    )

            await conn.commit()

        if recent or expired:
            logger.info("Missed recovery sweep: %d recent (recoverable), %d expired (missed).", len(recent), len(expired))
        return recent, expired

    # =========================================================================
    # 3. FOCUS SESSIONS MANAGEMENT
    # =========================================================================

    async def create_focus_session(self, item: FocusSessionCreate) -> FocusSessionItem:
        """Start a new focus session, automatically cancelling any active ones."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        import datetime as dt_module
        target_end_iso = (now + dt_module.timedelta(minutes=item.duration_minutes)).isoformat()

        async with aiosqlite.connect(self.db_path) as conn:
            # Cancel active sessions
            await conn.execute(
                "UPDATE focus_sessions SET status = 'CANCELLED', updated_at = ? WHERE status = 'ACTIVE';",
                (now_iso,),
            )
            query = """
            INSERT INTO focus_sessions (
                id, task_focus, duration_minutes, start_time_utc,
                target_end_time_utc, status, interruptions_count,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'ACTIVE', 0, ?, ?);
            """
            await conn.execute(query, (session_id, item.task_focus, item.duration_minutes, now_iso, target_end_iso, now_iso, now_iso))
            await conn.commit()

        logger.info("Started Focus Session '%s' (%d mins)", item.task_focus, item.duration_minutes)
        return FocusSessionItem(
            id=session_id,
            task_focus=item.task_focus,
            duration_minutes=item.duration_minutes,
            start_time_utc=now_iso,
            target_end_time_utc=target_end_iso,
            status=FocusSessionStatus.ACTIVE,
            interruptions_count=0,
            created_at=now_iso,
            updated_at=now_iso,
        )

    async def get_active_focus_session(self) -> Optional[FocusSessionItem]:
        """Fetch the currently active focus session if one exists."""
        query = "SELECT * FROM focus_sessions WHERE status = 'ACTIVE' ORDER BY start_time_utc DESC LIMIT 1;"
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query)
            row = await cursor.fetchone()
            if row:
                return self._row_to_focus(row)
        return None

    async def complete_focus_session(self, session_id: str, actual_end_time_utc: str) -> Optional[FocusSessionItem]:
        """Mark an active focus session as completed."""
        query = """
        UPDATE focus_sessions
        SET status = 'COMPLETED',
            actual_end_time_utc = ?,
            updated_at = ?
        WHERE id = ? AND status = 'ACTIVE';
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(query, (actual_end_time_utc, actual_end_time_utc, session_id))
            await conn.commit()

        return await self._get_focus_session_by_id(session_id)

    async def cancel_focus_session(self, session_id: str) -> Optional[FocusSessionItem]:
        """Cancel an active focus session early."""
        now = datetime.now(timezone.utc).isoformat()
        query = """
        UPDATE focus_sessions
        SET status = 'CANCELLED',
            actual_end_time_utc = ?,
            updated_at = ?
        WHERE id = ? AND status = 'ACTIVE';
        """
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(query, (now, now, session_id))
            await conn.commit()

        return await self._get_focus_session_by_id(session_id)

    async def _get_focus_session_by_id(self, session_id: str) -> Optional[FocusSessionItem]:
        query = "SELECT * FROM focus_sessions WHERE id = ?;"
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, (session_id,))
            row = await cursor.fetchone()
            if row:
                return self._row_to_focus(row)
        return None

    # =========================================================================
    # 4. SETTINGS & NOTIFICATION HISTORY
    # =========================================================================

    async def get_settings(self) -> ScheduleSettings:
        """Fetch all schedule and proactive settings."""
        query = "SELECT key, value FROM schedule_settings;"
        data: Dict[str, Any] = {}
        async with aiosqlite.connect(self.db_path) as conn:
            cursor = await conn.execute(query)
            rows = await cursor.fetchall()
            for k, v in rows:
                if v.lower() in ("true", "false"):
                    data[k] = v.lower() == "true"
                elif v.isdigit():
                    data[k] = int(v)
                else:
                    data[k] = v

        return ScheduleSettings(
            system_timezone=data.get("system_timezone", "Asia/Kolkata"),
            quiet_hours_enabled=data.get("quiet_hours_enabled", True),
            quiet_hours_start=data.get("quiet_hours_start", "23:00"),
            quiet_hours_end=data.get("quiet_hours_end", "07:00"),
            proactive_enabled=data.get("proactive_enabled", True),
            daily_briefing_enabled=data.get("daily_briefing_enabled", True),
            daily_briefing_time=data.get("daily_briefing_time", "08:30"),
            last_daily_briefing_date=data.get("last_daily_briefing_date", ""),
            lead_time_exam_days=data.get("lead_time_exam_days", 3),
            lead_time_assignment_days=data.get("lead_time_assignment_days", 1),
        )

    async def update_settings(self, updates: Dict[str, Any]) -> ScheduleSettings:
        """Update proactive schedule settings."""
        now = datetime.now(timezone.utc).isoformat()
        query = """
        INSERT INTO schedule_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at;
        """
        async with aiosqlite.connect(self.db_path) as conn:
            for k, v in updates.items():
                val_str = str(v).lower() if isinstance(v, bool) else str(v)
                await conn.execute(query, (k, val_str, now))
            await conn.commit()

        return await self.get_settings()

    async def save_settings(self, settings: ScheduleSettings) -> ScheduleSettings:
        """Persist a ScheduleSettings model instance."""
        return await self.update_settings(settings.model_dump())

    async def record_notification(self, item: NotificationCreate) -> NotificationHistoryItem:
        """Record an alert dispatch in notification history."""
        notif_id = str(uuid.uuid4())
        query = """
        INSERT INTO notification_history (
            id, reminder_id, title, body, category, channel,
            delivery_status, dispatched_at_utc, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            notif_id,
            item.reminder_id,
            item.title,
            item.body,
            item.category,
            item.channel.value,
            item.delivery_status.value,
            item.dispatched_at_utc,
            item.error_message,
        )
        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(query, params)
            await conn.commit()

        return NotificationHistoryItem(
            id=notif_id,
            reminder_id=item.reminder_id,
            title=item.title,
            body=item.body,
            category=item.category,
            channel=item.channel,
            delivery_status=item.delivery_status,
            dispatched_at_utc=item.dispatched_at_utc,
            error_message=item.error_message,
        )

    async def list_notifications(self, limit: int = 50) -> List[NotificationHistoryItem]:
        """Fetch recent notification history."""
        query = "SELECT * FROM notification_history ORDER BY dispatched_at_utc DESC LIMIT ?;"
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, (limit,))
            rows = await cursor.fetchall()
            return [
                NotificationHistoryItem(
                    id=r["id"],
                    reminder_id=r["reminder_id"],
                    title=r["title"],
                    body=r["body"],
                    category=r["category"],
                    channel=NotificationChannel(r["channel"]),
                    delivery_status=NotificationDeliveryStatus(r["delivery_status"]),
                    dispatched_at_utc=r["dispatched_at_utc"],
                    dismissed_at_utc=r["dismissed_at_utc"],
                    error_message=r["error_message"],
                )
                for r in rows
            ]

    # =========================================================================
    # Helpers
    # =========================================================================

    def _row_to_event(self, row: aiosqlite.Row) -> EventItem:
        return EventItem(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            category=EventCategory(row["category"]),
            priority=EventPriority(row["priority"]),
            event_date=row["event_date"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            timezone=row["timezone"],
            recurrence=EventRecurrence(row["recurrence"]),
            target_day_of_month=row["target_day_of_month"] or 0,
            recurrence_interval_days=row["recurrence_interval_days"] or 0,
            completion_status=EventCompletionStatus(row["completion_status"]),
            source=EventSource(row["source"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_deleted=bool(row["is_deleted"]),
        )

    def _row_to_reminder(self, row: aiosqlite.Row) -> ReminderItem:
        return ReminderItem(
            id=row["id"],
            event_id=row["event_id"],
            remind_at_utc=row["remind_at_utc"],
            remind_at_local=row["remind_at_local"],
            offset_minutes=row["offset_minutes"],
            title=row["title"],
            message=row["message"],
            priority=EventPriority(row["priority"]),
            status=ReminderStatus(row["status"]),
            claim_worker_id=row["claim_worker_id"],
            claimed_at_utc=row["claimed_at_utc"],
            dispatch_attempts=row["dispatch_attempts"],
            last_attempt_at=row["last_attempt_at"],
            delivered_at=row["delivered_at"],
            dismissed_at=row["dismissed_at"],
            snooze_until_utc=row["snooze_until_utc"],
            delivery_error=row["delivery_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_deleted=bool(row["is_deleted"]),
        )

    def _row_to_focus(self, row: aiosqlite.Row) -> FocusSessionItem:
        return FocusSessionItem(
            id=row["id"],
            task_focus=row["task_focus"],
            duration_minutes=row["duration_minutes"],
            start_time_utc=row["start_time_utc"],
            target_end_time_utc=row["target_end_time_utc"],
            actual_end_time_utc=row["actual_end_time_utc"],
            status=FocusSessionStatus(row["status"]),
            interruptions_count=row["interruptions_count"],
            notes=row["notes"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
