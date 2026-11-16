-- Migration 005: Voice Interaction Schema
-- PROJECT ZORO — Milestone 04: High-Speed Local Voice Interaction

CREATE TABLE IF NOT EXISTS voice_sessions (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,  -- 'ACTIVE', 'COMPLETED', 'INTERRUPTED', 'FAILED'
    input_device TEXT,
    output_device TEXT,
    stt_provider TEXT,
    tts_provider TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS voice_utterances (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    conversation_id TEXT,
    message_id TEXT,
    transcript TEXT NOT NULL,
    language TEXT DEFAULT 'en',
    recognition_duration_ms REAL DEFAULT 0.0,
    processing_status TEXT NOT NULL,  -- 'RECOGNIZED', 'PROCESSED', 'REJECTED'
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES voice_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS voice_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES voice_sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS voice_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Indices for rapid query performance
CREATE INDEX IF NOT EXISTS idx_voice_utterances_session ON voice_utterances(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_utterances_created ON voice_utterances(created_at);
CREATE INDEX IF NOT EXISTS idx_voice_metrics_session ON voice_metrics(session_id);
CREATE INDEX IF NOT EXISTS idx_voice_metrics_name ON voice_metrics(metric_name);
