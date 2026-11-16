-- Migration 004: Windows Computer Control, UI Automation & Execution Sandbox
-- Project ZORO

CREATE TABLE IF NOT EXISTS computer_sessions (
    id TEXT PRIMARY KEY,
    profile TEXT NOT NULL DEFAULT 'PROFILE_B_STANDARD',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    user_approved INTEGER NOT NULL DEFAULT 1,
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS computer_actions (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES computer_sessions(id) ON DELETE CASCADE,
    action_type TEXT NOT NULL,
    target TEXT,
    parameters_json TEXT,
    risk_tier TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    verified INTEGER NOT NULL DEFAULT 0,
    confidence REAL DEFAULT 0.0,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_computer_actions_session ON computer_actions(session_id);
CREATE INDEX IF NOT EXISTS idx_computer_actions_created ON computer_actions(created_at);

CREATE TABLE IF NOT EXISTS shell_executions (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES computer_sessions(id) ON DELETE SET NULL,
    command TEXT NOT NULL,
    args_json TEXT NOT NULL,
    returncode INTEGER NOT NULL,
    stdout TEXT,
    stderr TEXT,
    duration_seconds REAL NOT NULL,
    risk_tier TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shell_executions_created ON shell_executions(created_at);

CREATE TABLE IF NOT EXISTS app_registry (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    executable_path TEXT,
    publisher TEXT,
    version TEXT,
    last_scanned_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS screenshot_metadata (
    id TEXT PRIMARY KEY,
    session_id TEXT REFERENCES computer_sessions(id) ON DELETE SET NULL,
    file_path TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    monitor_idx INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_screenshots_session ON screenshot_metadata(session_id);
