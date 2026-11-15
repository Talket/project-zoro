"""Tests for zoro.__main__ CLI argument parsing and entry points."""

import sys
from unittest.mock import patch
import pytest
from zoro.__main__ import main
from zoro.security.emergency import EmergencyManager


def test_main_cli_halt_exit(test_settings, monkeypatch):
    """Verify main() immediately exits with status 1 if halt lock exists."""
    test_settings.halt_lock_path.parent.mkdir(parents=True, exist_ok=True)
    test_settings.halt_lock_path.write_text('{"reason": "Lock active"}', encoding="utf-8")

    monkeypatch.setattr("zoro.config.settings.get_settings", lambda: test_settings)
    monkeypatch.setattr("zoro.__main__.EmergencyManager", lambda: EmergencyManager(halt_lock_path=test_settings.halt_lock_path))
    monkeypatch.setattr(sys, "argv", ["zoro", "--headless"])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1


def test_main_cli_headless_dispatch(test_settings, monkeypatch):
    """Verify --headless flag routes to ZoroEngine.run()."""
    # Ensure no halt lock
    if test_settings.halt_lock_path.exists():
        test_settings.halt_lock_path.unlink()

    monkeypatch.setattr("zoro.config.settings.get_settings", lambda: test_settings)
    monkeypatch.setattr("zoro.__main__.EmergencyManager", lambda: EmergencyManager(halt_lock_path=test_settings.halt_lock_path))
    monkeypatch.setattr(sys, "argv", ["zoro", "--headless", "--debug"])

    ran = []

    async def mock_run(self):
        ran.append(True)

    with patch("zoro.core.engine.ZoroEngine.run", mock_run):
        main()

    assert ran == [True]


def test_main_cli_ui_dispatch(test_settings, monkeypatch):
    """Verify --ui flag routes to ZoroDesktopApp.run()."""
    if test_settings.halt_lock_path.exists():
        test_settings.halt_lock_path.unlink()

    monkeypatch.setattr("zoro.config.settings.get_settings", lambda: test_settings)
    monkeypatch.setattr("zoro.__main__.EmergencyManager", lambda: EmergencyManager(halt_lock_path=test_settings.halt_lock_path))
    monkeypatch.setattr(sys, "argv", ["zoro", "--ui"])

    app_ran = []

    with patch("zoro.ui.app.ZoroDesktopApp.run", lambda self: 0):
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0


def test_run_engine_async_helper():
    """Verify run_engine_async creates event loop and runs engine.run()."""
    from zoro.__main__ import run_engine_async

    class MockEngine:
        def __init__(self):
            self.ran = False

        async def run(self):
            self.ran = True

    mock_engine = MockEngine()
    run_engine_async(mock_engine)
    assert mock_engine.ran is True
