-- Migration 002: Audit Records and Health Metrics

CREATE TABLE IF NOT EXISTS audit_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    resource TEXT NOT NULL,
    details_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    record_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_records (timestamp);

CREATE TABLE IF NOT EXISTS health_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    cpu_percent REAL NOT NULL,
    ram_used_mb REAL NOT NULL,
    ram_total_mb REAL NOT NULL,
    gpu_vram_used_mb REAL,
    gpu_vram_total_mb REAL,
    gpu_temp_c REAL,
    gpu_utilization_percent REAL,
    disk_free_gb REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_health_timestamp ON health_metrics (timestamp);
