"""Deterministic Daily Briefing Generator for PROJECT ZORO Milestone 06.

Aggregates confirmed timetable events, upcoming deadlines, overdue tasks,
and prioritized action summaries without LLM hallucination.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

from zoro.schedule.models import (
    DailyBriefing,
    DeadlineItem,
    EventItem,
    ScheduleSettings,
)
from zoro.schedule.timetable import TimetableManager

logger = logging.getLogger(__name__)


class DailyBriefingGenerator:
    """Constructs deterministic operational briefings from confirmed SQLite data."""

    def __init__(self, timetable_mgr: TimetableManager) -> None:
        self.timetable_mgr = timetable_mgr

    async def generate_briefing(self, settings: Optional[ScheduleSettings] = None) -> DailyBriefing:
        """Assemble complete operational situational briefing."""
        cfg = settings or await self.timetable_mgr.store.get_settings()
        tz = ZoneInfo(cfg.system_timezone)
        now_local = datetime.now(tz)
        today_date_str = now_local.strftime("%Y-%m-%d")
        now_time_str = now_local.strftime("%I:%M %p")
        day_name = now_local.strftime("%A, %B %d, %Y")

        greeting = f"Good morning, Sir. Here is your operational briefing for {day_name}."

        # 1. Fetch Today's Agenda
        todays_events = await self.timetable_mgr.get_todays_agenda()

        # 2. Fetch Upcoming Deadlines (within next 72 hours)
        upcoming_deadlines = await self.timetable_mgr.get_upcoming_deadlines(horizon_days=3)

        # 3. Fetch Overdue Tasks
        overdue_tasks = await self.timetable_mgr.get_overdue_tasks()

        # 4. Synthesize Deterministic Summary Text
        lines = [greeting, ""]

        # Section: Today's Schedule
        if todays_events:
            lines.append("📅 TODAY'S AGENDA:")
            for ev in todays_events:
                t_str = f"at {ev.start_time}" if ev.start_time else "all-day"
                lines.append(f"  • [{ev.category.value}] {ev.title} ({t_str}) - Priority: {ev.priority.value}")
        else:
            lines.append("📅 TODAY'S AGENDA:\n  • No scheduled events today. Clear schedule.")

        lines.append("")

        # Section: Upcoming Deadlines
        if upcoming_deadlines:
            lines.append("⏳ UPCOMING DEADLINES (Next 72 Hours):")
            for d in upcoming_deadlines[:4]:
                status_txt = "OVERDUE" if d.is_overdue else f"{d.hours_remaining:.0f} hours remaining"
                t_str = f" {d.due_time}" if d.due_time else ""
                lines.append(f"  • {d.title} (Due: {d.due_date}{t_str}) — {status_txt}")
            lines.append("")

        # Section: Overdue Tasks
        if overdue_tasks:
            lines.append("⚠️ OVERDUE ACTION ITEMS:")
            for od in overdue_tasks[:3]:
                lines.append(f"  • {od.title} (From: {od.event_date}) — Priority: {od.priority.value}")
            lines.append("")

        # Section: Top 3 Priorities
        top_priorities: List[str] = []
        # Combine overdue and highest urgency deadlines
        for od in overdue_tasks[:2]:
            top_priorities.append(f"Resolve overdue item: '{od.title}'")
        for d in upcoming_deadlines:
            if len(top_priorities) >= 3:
                break
            top_priorities.append(f"Address deadline: '{d.title}' ({d.hours_remaining:.0f}h remaining)")

        if top_priorities:
            lines.append("🎯 TOP PRIORITIES:")
            for idx, p in enumerate(top_priorities, 1):
                lines.append(f"  {idx}. {p}")
        else:
            lines.append("🎯 TOP PRIORITIES:\n  All items currently on track, Sir.")

        summary_text = "\n".join(lines)

        return DailyBriefing(
            briefing_date=today_date_str,
            generated_at=now_local.isoformat(),
            greeting=greeting,
            summary_text=summary_text,
            todays_events=todays_events,
            upcoming_deadlines=upcoming_deadlines,
            overdue_tasks=overdue_tasks,
        )
