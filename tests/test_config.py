"""Tests for configuration management and path resolution."""

import os
from pathlib import Path
from zoro.config.paths import AppPaths
from zoro.config.settings import ZoroSettings, get_settings


def test_paths_resolution(temp_dir):
    paths = AppPaths(custom_data_dir=temp_dir)
    assert paths.data_dir == temp_dir
    assert paths.logs_dir == temp_dir / "logs"
    assert paths.db_path == temp_dir / "zoro.db"
    assert paths.pid_path == temp_dir / "zoro.pid"
    
    paths.ensure_directories()
    assert paths.data_dir.exists()
    assert paths.logs_dir.exists()


def test_settings_defaults(test_settings):
    assert test_settings.app_name == "PROJECT ZORO"
    assert test_settings.app_env == "testing"
    assert test_settings.db_wal_mode is True
    assert test_settings.max_vram_mb == 3600
    assert test_settings.max_ram_mb == 13800


def test_settings_env_override(monkeypatch, temp_dir):
    monkeypatch.setenv("ZORO_APP_ENV", "staging")
    monkeypatch.setenv("ZORO_MAX_VRAM_MB", "3200")
    settings = ZoroSettings(data_dir=temp_dir)
    assert settings.app_env == "staging"
    assert settings.max_vram_mb == 3200
