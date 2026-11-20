"""Deterministic Temporal Parser & Recurrence Calculator for PROJECT ZORO Milestone 06.

Provides deterministic date/time resolution, ambiguity detection,
timezone conversions, and non-drifting monthly recurrence clamping.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo


@dataclass
class TemporalParseResult:
    """Container for parsed scheduling temporal parameters."""
    event_date: Optional[str] = None          # YYYY-MM-DD
    start_time: Optional[str] = None          # HH:MM
    end_time: Optional[str] = None            # HH:MM
    duration_minutes: Optional[int] = None    # for focus sessions
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    extracted_title: Optional[str] = None
    reminder_offset_minutes: int = 0          # default at event


class TemporalParser:
    """Deterministic natural-language temporal expression parser."""

    MONTHS = {
        "january": 1, "jan": 1,
        "february": 2, "feb": 2,
        "march": 3, "mar": 3,
        "april": 4, "apr": 4,
        "may": 5,
        "june": 6, "jun": 6,
        "july": 7, "jul": 7,
        "august": 8, "aug": 8,
        "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10,
        "november": 11, "nov": 11,
        "december": 12, "dec": 12,
    }

    WEEKDAYS = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tue": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thu": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }

    def __init__(self, default_timezone: str = "Asia/Kolkata") -> None:
        self.default_timezone = default_timezone

    def get_tz(self) -> Any:
        try:
            return ZoneInfo(self.default_timezone)
        except Exception:
            return timezone.utc

    def now_local(self) -> datetime:
        return datetime.now(self.get_tz())

    def parse_scheduling_prompt(self, text: str) -> TemporalParseResult:
        """
        Extract date, time, duration, and title from natural language user prompt.
        Detects ambiguity if a command requests a reminder/event but omits temporal details.
        """
        raw = text.strip()
        low = raw.lower()

        # Check for focus session duration
        focus_match = re.search(r"(\d+)[ -]?(minute|min|hour|hr)s?\s*(?:focus|session|timer)?", low)
        if "focus" in low and focus_match:
            val = int(focus_match.group(1))
            unit = focus_match.group(2)
            mins = val * 60 if "hour" in unit or "hr" in unit else val
            return TemporalParseResult(duration_minutes=mins)

        # 1. Parse time expression (e.g. "at 9 AM", "at 9:30 am", "at 14:00", "at 2 PM")
        parsed_time, text_sans_time = self._extract_time(low)

        # 2. Parse date expression (e.g. "tomorrow", "today", "on Dec 12", "in 30 mins")
        parsed_date, relative_offset_mins = self._extract_date(text_sans_time)

        # If a relative offset in minutes was requested ("in 30 minutes")
        if relative_offset_mins is not None:
            target_dt = self.now_local() + timedelta(minutes=relative_offset_mins)
            parsed_date = target_dt.strftime("%Y-%m-%d")
            parsed_time = target_dt.strftime("%H:%M")

        # 3. Detect Ambiguity: If the user says "remind me to...", but no date and no time was found
        if parsed_date is None and parsed_time is None:
            # Check if this is an explicit scheduling command
            scheduling_intents = ["remind me to", "remind me about", "schedule a", "create event", "set a reminder"]
            if any(intent in low for intent in scheduling_intents):
                return TemporalParseResult(
                    is_ambiguous=True,
                    ambiguity_reason="Missing date and time for the requested reminder.",
                )

        # Default date to today if time is specified but date is omitted
        if parsed_time is not None and parsed_date is None:
            now = self.now_local()
            parsed_hour, parsed_min = map(int, parsed_time.split(":"))
            if time(parsed_hour, parsed_min) < now.time():
                # If time has already passed today, assume tomorrow
                parsed_date = (now.date() + timedelta(days=1)).strftime("%Y-%m-%d")
            else:
                parsed_date = now.date().strftime("%Y-%m-%d")

        # Extract title by stripping out known temporal phrases
        title = self._clean_title(raw)

        # Check for reminder offset (e.g. "remind me 30 minutes before")
        offset = 0
        offset_match = re.search(r"(\d+)\s*(?:minute|min)s?\s*before", low)
        if offset_match:
            offset = int(offset_match.group(1))

        return TemporalParseResult(
            event_date=parsed_date,
            start_time=parsed_time,
            extracted_title=title,
            reminder_offset_minutes=offset,
        )

    def _extract_time(self, text: str) -> Tuple[Optional[str], str]:
        """Match and extract HH:MM or 12-hour AM/PM time."""
        # 1. 12-hour AM/PM: e.g. "9:30 am", "9 am", "11:59 pm"
        m1 = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
        if m1:
            hour = int(m1.group(1))
            minute = int(m1.group(2) or 0)
            meridiem = m1.group(3)
            if meridiem == "pm" and hour != 12:
                hour += 12
            elif meridiem == "am" and hour == 12:
                hour = 0
            time_str = f"{hour:02d}:{minute:02d}"
            cleaned = text[: m1.start()] + text[m1.end() :]
            return time_str, cleaned

        # 2. 24-hour military: e.g. "14:00", "09:30"
        m2 = re.search(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b", text)
        if m2:
            time_str = f"{int(m2.group(1)):02d}:{int(m2.group(2)):02d}"
            cleaned = text[: m2.start()] + text[m2.end() :]
            return time_str, cleaned

        return None, text

    def _extract_date(self, text: str) -> Tuple[Optional[str], Optional[int]]:
        """Match and extract YYYY-MM-DD or relative offset in minutes."""
        now = self.now_local()
        today = now.date()

        # Relative minutes: "in 20 minutes", "in 1 hour"
        rel_match = re.search(r"\bin\s+(\d+)\s*(minute|min|hour|hr)s?\b", text)
        if rel_match:
            qty = int(rel_match.group(1))
            unit = rel_match.group(2)
            mins = qty * 60 if "hour" in unit or "hr" in unit else qty
            return None, mins

        if "tomorrow" in text:
            return (today + timedelta(days=1)).strftime("%Y-%m-%d"), None
        if "day after tomorrow" in text:
            return (today + timedelta(days=2)).strftime("%Y-%m-%d"), None
        if "today" in text:
            return today.strftime("%Y-%m-%d"), None

        # Named weekday: "next monday", "on friday"
        for name, target_idx in self.WEEKDAYS.items():
            pattern = rf"\b(?:next\s+|on\s+)?{name}\b"
            if re.search(pattern, text):
                current_idx = today.weekday()
                days_ahead = (target_idx - current_idx) % 7
                if days_ahead == 0:
                    days_ahead = 7
                return (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d"), None

        # Absolute Month + Day: e.g. "december 12", "on dec 12th", "12 december"
        for m_name, m_num in self.MONTHS.items():
            # "December 12" or "Dec 12th"
            p1 = rf"\b{m_name}\s+(\d{{1,2}})(?:st|nd|rd|th)?\b"
            m1 = re.search(p1, text)
            if m1:
                day = int(m1.group(1))
                year = today.year
                # Validate date
                try:
                    d = date(year, m_num, day)
                    if d < today:
                        # If date already passed this year, assign to next year
                        d = date(year + 1, m_num, day)
                    return d.strftime("%Y-%m-%d"), None
                except ValueError:
                    return None, None

            # "12th of December" or "12 December"
            p2 = rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{m_name}\b"
            m2 = re.search(p2, text)
            if m2:
                day = int(m2.group(1))
                year = today.year
                try:
                    d = date(year, m_num, day)
                    if d < today:
                        d = date(year + 1, m_num, day)
                    return d.strftime("%Y-%m-%d"), None
                except ValueError:
                    return None, None

        # Standard YYYY-MM-DD
        iso_m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
        if iso_m:
            try:
                d = date(int(iso_m.group(1)), int(iso_m.group(2)), int(iso_m.group(3)))
                return d.strftime("%Y-%m-%d"), None
            except ValueError:
                return None, None

        return None, None

    def _clean_title(self, raw_text: str) -> str:
        """Strip command prefixes and temporal markers to isolate the task title."""
        cleaned = raw_text
        # Strip prefixes
        cleaned = re.sub(r"^(?:zoro,?\s*)?(?:please\s+)?(?:remind me\s+(?:tomorrow|today|at\s+[\d:]+\s*(?:am|pm)?)?\s*to\s+)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:i have an?\s+)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:remember it|schedule it|save it)\b\.?", "", cleaned, flags=re.IGNORECASE)
        # Strip remaining temporal fragments at ends
        cleaned = re.sub(r"\b(?:tomorrow|today|yesterday)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\b(?:on\s+[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?)\b", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip(" .,!?:;")
        return cleaned or "Scheduled Reminder"

    # =========================================================================
    # Non-Drifting Monthly Recurrence Clamping
    # =========================================================================

    @staticmethod
    def calculate_next_monthly_occurrence(
        current_date: Any = None,
        target_day_of_month: int = 31,
        current_date_str: Optional[str] = None,
    ) -> Any:
        """
        Advance one month while strictly preserving the target day of month.
        Supports both date objects and ISO date strings.
        
        Example:
            target_day_of_month = 31
            Jan 31 -> Feb 28 (or Feb 29 in leap year)
            Feb 28 -> Mar 31  (RESTORES original 31st, ZERO DRIFT)
            Mar 31 -> Apr 30
            Apr 30 -> May 31
        """
        raw = current_date_str if current_date_str is not None else current_date
        is_str_input = isinstance(raw, str)
        if is_str_input:
            parts = list(map(int, raw.split("-")))
            c_date = date(parts[0], parts[1], parts[2])
        else:
            c_date = raw

        if c_date.month == 12:
            next_year = c_date.year + 1
            next_month = 1
        else:
            next_year = c_date.year
            next_month = c_date.month + 1

        _, max_days = calendar.monthrange(next_year, next_month)
        # Clamp to max days in month without altering target_day_of_month for subsequent months
        next_day = min(target_day_of_month, max_days)
        res_date = date(next_year, next_month, next_day)
        if is_str_input:
            return res_date.strftime("%Y-%m-%d"), target_day_of_month
        return res_date

    def calculate_remind_at_utc(
        self,
        event_date_str: str,
        start_time_str: Optional[str],
        offset_minutes: int = 0,
        event_timezone: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Convert local event date + time and reminder offset into:
        (remind_at_utc_iso, remind_at_local_iso)
        """
        tz = ZoneInfo(event_timezone or self.default_timezone)
        d_parts = list(map(int, event_date_str.split("-")))
        t_parts = list(map(int, start_time_str.split(":"))) if start_time_str else [9, 0]

        local_dt = datetime(d_parts[0], d_parts[1], d_parts[2], t_parts[0], t_parts[1], tzinfo=tz)
        remind_local_dt = local_dt - timedelta(minutes=offset_minutes)
        remind_utc_dt = remind_local_dt.astimezone(timezone.utc)

        return remind_utc_dt.isoformat(), remind_local_dt.strftime("%Y-%m-%d %H:%M:%S")
