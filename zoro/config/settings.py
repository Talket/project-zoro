"""Pydantic v2 application settings and configuration management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from zoro.config.paths import default_paths


class ZoroSettings(BaseSettings):
    """Central configuration for PROJECT ZORO."""

    model_config = SettingsConfigDict(
        env_prefix="ZORO_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    app_name: str = "PROJECT ZORO"
    app_env: str = "production"  # development, testing, production
    log_level: str = "INFO"      # DEBUG, INFO, WARNING, ERROR
    instance_id: str = "zoro-primary"
    debug: bool = False

    # Directories and Paths
    data_dir: Path = Field(default_factory=lambda: default_paths.data_dir)
    logs_dir: Path = Field(default_factory=lambda: default_paths.logs_dir)
    db_path: Path = Field(default_factory=lambda: default_paths.db_path)
    security_dir: Path = Field(default_factory=lambda: default_paths.security_dir)
    halt_lock_path: Path = Field(default_factory=lambda: default_paths.halt_lock_path)
    pid_path: Path = Field(default_factory=lambda: default_paths.pid_path)
    audit_checkpoint_path: Path = Field(default_factory=lambda: default_paths.audit_checkpoint_path)

    # Hardware & Telemetry Thresholds
    max_vram_mb: int = 3600               # VRAM ceiling for 4GB GTX 1050 Ti
    max_ram_mb: int = 13800               # Host RAM threshold (16GB total)
    max_cpu_percent: float = 85.0         # Continuous CPU threshold
    model_idle_timeout_sec: int = 600     # 10 minutes idle before VRAM eviction
    telemetry_interval_sec: float = 1.0   # Hardware sampling rate

    # Inter-Process Communication (IPC)
    pipe_name: str = Field(default_factory=lambda: default_paths.ipc_pipe_name)
    ipc_max_payload_mb: int = 16
    ipc_heartbeat_interval_sec: float = 2.0
    ipc_reconnect_max_backoff_sec: float = 10.0

    # Storage & SQLite
    db_wal_mode: bool = True
    db_busy_timeout_ms: int = 5000
    db_cache_size_kb: int = 8000          # 8 MB SQLite page cache
    db_synchronous: str = "NORMAL"

    # Security (Keys are strictly DPAPI-protected; audit_hmac_key is optional legacy override for testing only)
    audit_enabled: bool = True
    audit_hmac_key: Optional[str] = None
    strict_permissions: bool = True

    # Desktop UI
    ui_theme: str = "dark_obsidian"
    ui_start_minimized: bool = False
    ui_window_width: int = 1024
    ui_window_height: int = 680

    # AI Models (Milestone 2 defaults)
    model_provider: str = "llama_server"  # llama_server, ollama, mock
    primary_model: str = "qwen2.5:3b-instruct"
    fallback_model: str = "qwen2.5:1.5b-instruct"
    coder_model: str = "qwen2.5-coder:7b-instruct"
    llama_server_path: Optional[str] = None
    ollama_url: str = "http://127.0.0.1:11434"


def get_settings() -> ZoroSettings:
    """Retrieve settings instance, ensuring directories exist."""
    settings = ZoroSettings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    try:
        settings.security_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return settings
