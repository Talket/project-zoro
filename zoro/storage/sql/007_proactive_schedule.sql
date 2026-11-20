-- Migration 007: Proactive Intelligence & Timetable Awareness Subsystem
-- PROJECT ZORO — Milestone 06: Timetable, Reminders, Focus Mode & Native Notifications

-- 1. Events Table (Decoupled from reminders, 1-to-many relationship)
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL CHECK(category IN ('COLLEGE', 'EXAMS', 'ASSIGNMENTS', 'PROJECTS', 'PERSONAL', 'MEETINGS', 'GENERAL_TASKS')),
    priority TEXT NOT NULL DEFAULT 'MEDIUM' CHECK(priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
    event_date TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    recurrence TEXT NOT NULL DEFAULT 'NONE' CHECK(recurrence IN ('NONE', 'DAILY', 'WEEKLY', 'WEEKDAYS', 'MONTHLY', 'CUSTOM')),
    target_day_of_month INTEGER DEFAULT 0,
    recurrence_interval_days INTEGER DEFAULT 0,
    completion_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(completion_status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'OVERDUE')),
    source TEXT NOT NULL DEFAULT 'user_command' CHECK(source IN ('user_command', 'voice_command', 'extracted_memory', 'proactive_engine', 'ui_manual')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0, 1))
);

-- 2. Reminders Table (Crash-Safe Dispatch with CLAIMED state & atomic locking)
CREATE TABLE IF NOT EXISTS reminders (
    id TEXT PRIMARY KEY,
    event_id TEXT REFERENCES events(id) ON DELETE CASCADE,
    remind_at_utc TEXT NOT NULL,
    remind_at_local TEXT NOT NULL,
    offset_minutes INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'MEDIUM' CHECK(priority IN ('LOW', 'MEDIUM', 'HIGH', 'URGENT')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING', 'CLAIMED', 'DELIVERED', 'DISMISSED', 'SNOOZED', 'MISSED', 'CANCELLED', 'FAILED')),
    claim_worker_id TEXT,
    claimed_at_utc TEXT,
    dispatch_attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    delivered_at TEXT,
    dismissed_at TEXT,
    snooze_until_utc TEXT,
    delivery_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0, 1))
);

-- 3. Focus Sessions Table
CREATE TABLE IF NOT EXISTS focus_sessions (
    id TEXT PRIMARY KEY,
    task_focus TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    start_time_utc TEXT NOT NULL,
    target_end_time_utc TEXT NOT NULL,
    actual_end_time_utc TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE', 'COMPLETED', 'CANCELLED')),
    interruptions_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 4. Schedule & Proactive Settings Key-Value Table
CREATE TABLE IF NOT EXISTS schedule_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Default proactive settings
INSERT OR IGNORE INTO schedule_settings (key, value, updated_at) VALUES 
    ('system_timezone', 'Asia/Kolkata', datetime('now')),
    ('quiet_hours_enabled', 'true', datetime('now')),
    ('quiet_hours_start', '23:00', datetime('now')),
    ('quiet_hours_end', '07:00', datetime('now')),
    ('proactive_enabled', 'true', datetime('now')),
    ('daily_briefing_enabled', 'true', datetime('now')),
    ('daily_briefing_time', '08:30', datetime('now')),
    ('last_daily_briefing_date', '', datetime('now')),
    ('lead_time_exam_days', '3', datetime('now')),
    ('lead_time_assignment_days', '1', datetime('now'));

-- 5. Notification History Table (Persistent delivery auditing & fallback tracking)
CREATE TABLE IF NOT EXISTS notification_history (
    id TEXT PRIMARY KEY,
    reminder_id TEXT REFERENCES reminders(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    category TEXT NOT NULL,
    channel TEXT NOT NULL CHECK(channel IN ('WINDOWS_TOAST', 'SYSTEM_TRAY', 'HUD_CONSOLE', 'VOICE_TTS')),
    delivery_status TEXT NOT NULL CHECK(delivery_status IN ('SUCCESS', 'FALLBACK', 'SUPPRESSED_QUIET_HOURS', 'FAILED')),
    dispatched_at_utc TEXT NOT NULL,
    dismissed_at_utc TEXT,
    error_message TEXT
);

-- Indices for high-frequency scheduler queries & deadline scans
CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_events_status ON events(completion_status) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_events_priority ON events(priority) WHERE is_deleted = 0;

CREATE INDEX IF NOT EXISTS idx_reminders_remind_utc ON reminders(remind_at_utc) WHERE is_deleted = 0 AND status IN ('PENDING', 'SNOOZED');
CREATE INDEX IF NOT EXISTS idx_reminders_claimed ON reminders(status, claimed_at_utc) WHERE is_deleted = 0 AND status = 'CLAIMED';
CREATE INDEX IF NOT EXISTS idx_reminders_event_id ON reminders(event_id) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status) WHERE is_deleted = 0;

CREATE INDEX IF NOT EXISTS idx_focus_status ON focus_sessions(status);
CREATE INDEX IF NOT EXISTS idx_notifications_dispatched ON notification_history(dispatched_at_utc);
