-- Migration 001: Initial Core Schema

CREATE TABLE IF NOT EXISTS system_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    category TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON system_events (timestamp);
CREATE INDEX IF NOT EXISTS idx_events_category ON system_events (category);

CREATE TABLE IF NOT EXISTS config_entries (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
