-- Migration 006: Persistent Personal Memory Architecture
-- PROJECT ZORO — Milestone 05: Multi-Tiered Personal Memory & Semantic Search

CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK(category IN ('IDENTITY', 'PREFERENCE', 'EPISODIC', 'PROJECT', 'SCHEDULE')),
    content TEXT NOT NULL,
    summary TEXT,
    importance REAL NOT NULL DEFAULT 0.5 CHECK(importance >= 0.0 AND importance <= 1.0),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence >= 0.0 AND confidence <= 1.0),
    source TEXT NOT NULL DEFAULT 'extracted_conversation' CHECK(source IN ('explicit_user', 'extracted_conversation', 'system', 'user_edit')),
    project_name TEXT,
    event_timestamp TEXT,
    event_status TEXT DEFAULT 'PLANNED' CHECK(event_status IN ('PLANNED', 'COMPLETED', 'CANCELLED', 'IN_PROGRESS', 'ARCHIVED')),
    metadata_json TEXT DEFAULT '{}',
    embedding BLOB,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0, 1))
);

-- Full Text Search 5 (FTS5) for keyword and hybrid search
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED,
    category,
    content,
    project_name,
    content='memories',
    content_rowid='rowid'
);

-- Triggers to automatically keep FTS5 synchronized with the memories table
CREATE TRIGGER IF NOT EXISTS trg_memories_after_insert AFTER INSERT ON memories
WHEN new.is_deleted = 0
BEGIN
    INSERT INTO memories_fts(rowid, id, category, content, project_name)
    VALUES (new.rowid, new.id, new.category, new.content, new.project_name);
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_after_update AFTER UPDATE ON memories
BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, category, content, project_name)
    VALUES ('delete', old.rowid, old.id, old.category, old.content, old.project_name);
    INSERT INTO memories_fts(rowid, id, category, content, project_name)
    SELECT new.rowid, new.id, new.category, new.content, new.project_name
    WHERE new.is_deleted = 0;
END;

CREATE TRIGGER IF NOT EXISTS trg_memories_after_delete AFTER DELETE ON memories
BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, id, category, content, project_name)
    VALUES ('delete', old.rowid, old.id, old.category, old.content, old.project_name);
END;

-- Rapid query indices
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_name) WHERE is_deleted = 0;
CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance);
CREATE INDEX IF NOT EXISTS idx_memories_is_deleted ON memories(is_deleted);
