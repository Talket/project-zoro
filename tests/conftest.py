"""Shared pytest fixtures for PROJECT ZORO test suite."""

import asyncio
from pathlib import Path
import shutil
import tempfile
import uuid
import pytest

from zoro.config.settings import ZoroSettings
from zoro.storage.db import DatabaseManager


@pytest.fixture
def temp_dir():
    """Create and yield an isolated temporary directory for test storage."""
    d = tempfile.mkdtemp(prefix="zoro_test_")
    yield Path(d)
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def test_settings(temp_dir):
    """Provide isolated test settings pointing to the temp directory."""
    pipe_id = uuid.uuid4().hex[:8]
    return ZoroSettings(
        app_env="testing",
        data_dir=temp_dir / "data",
        logs_dir=temp_dir / "logs",
        db_path=temp_dir / "data" / "test_zoro.db",
        security_dir=temp_dir / "security",
        halt_lock_path=temp_dir / "security" / "halt.lock",
        pid_path=temp_dir / "zoro.pid",
        audit_checkpoint_path=temp_dir / "security" / "audit.checkpoint",
        pipe_name=rf"\\.\pipe\zoro-test-{pipe_id}",
        audit_hmac_key="test-secret-key-12345",
        telemetry_interval_sec=0.1,
    )


@pytest.fixture
async def test_db(test_settings):
    """Provide an initialized DatabaseManager instance with clean migrations."""
    db = DatabaseManager(db_path=test_settings.db_path, settings=test_settings)
    await db.initialize()
    yield db
    await db.close()
