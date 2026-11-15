-- Migration 003: Intelligence Core Schema
-- Tables for AI providers, models, benchmarks, conversations, task plans, tool executions, and approvals.

CREATE TABLE IF NOT EXISTS ai_providers (
    id TEXT PRIMARY KEY,
    provider_type TEXT NOT NULL,
    base_url TEXT NOT NULL,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    default_model TEXT,
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_models (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES ai_providers(id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    context_window INTEGER DEFAULT 4096,
    parameter_size TEXT,
    quantization TEXT,
    is_local INTEGER NOT NULL DEFAULT 1,
    capabilities_json TEXT NOT NULL DEFAULT '{}',
    discovered_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ai_models_provider ON ai_models (provider_id);

CREATE TABLE IF NOT EXISTS model_benchmarks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    ttft_ms REAL,
    tokens_per_sec REAL,
    ram_used_mb REAL,
    vram_used_mb REAL,
    gpu_temp_c REAL,
    structured_json_score REAL,
    instruction_following_score REAL,
    tool_calling_supported INTEGER DEFAULT 0,
    raw_metrics_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_benchmarks_model ON model_benchmarks (model_name);
CREATE INDEX IF NOT EXISTS idx_benchmarks_timestamp ON model_benchmarks (timestamp);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls_json TEXT,
    tool_call_id TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages (conversation_id);

CREATE TABLE IF NOT EXISTS task_plans (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE SET NULL,
    user_request TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_plans_status ON task_plans (status);

CREATE TABLE IF NOT EXISTS task_steps (
    id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL REFERENCES task_plans(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    description TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT,
    status TEXT NOT NULL,
    error TEXT,
    requires_approval INTEGER NOT NULL DEFAULT 0,
    approval_token TEXT,
    started_at TEXT,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_task_steps_plan ON task_steps (plan_id);

CREATE TABLE IF NOT EXISTS tool_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name TEXT NOT NULL,
    step_id TEXT,
    input_json TEXT NOT NULL,
    output_json TEXT,
    status TEXT NOT NULL,
    error TEXT,
    duration_ms REAL,
    executed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_exec_name ON tool_executions (tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_exec_time ON tool_executions (executed_at);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    step_id TEXT,
    tool_name TEXT NOT NULL,
    permission_tier TEXT NOT NULL,
    description TEXT NOT NULL,
    token TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    requested_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_approval_token ON approval_requests (token);
CREATE INDEX IF NOT EXISTS idx_approval_status ON approval_requests (status);
