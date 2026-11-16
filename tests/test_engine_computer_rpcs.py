"""Tests for ZoroEngine Computer Control RPC methods."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from zoro.config.settings import ZoroSettings
from zoro.core.engine import ZoroEngine


@pytest.fixture
async def direct_engine(tmp_path: Path):
    settings = ZoroSettings(
        data_dir=tmp_path,
        pipe_name=rf"\\.\pipe\test-rpc-{tmp_path.name}",
        db_path=tmp_path / "engine_rpc.db",
        security_dir=tmp_path / "sec",
        audit_checkpoint_path=tmp_path / "sec" / "audit.checkpoint",
        halt_lock_path=tmp_path / "sec" / "halt.lock",
        pid_path=tmp_path / "sec" / "zoro.pid",
    )
    (tmp_path / "sec").mkdir(parents=True, exist_ok=True)
    engine = ZoroEngine(settings=settings)
    await engine.initialize()
    yield engine, tmp_path
    await engine.shutdown()


@pytest.mark.asyncio
async def test_all_computer_rpcs(direct_engine):
    engine, tmp_path = direct_engine

    # 1. Profile RPCs
    p_get = await engine._rpc_computer_get_profile({})
    assert "profile" in p_get
    p_set = await engine._rpc_computer_set_profile({"profile": "PROFILE_C_RESTRICTED_MODIFICATION"})
    assert p_set["success"] is True
    p_bad = await engine._rpc_computer_set_profile({"profile": "INVALID_PROFILE_XYZ"})
    assert p_bad["success"] is False

    # 2. Resource status
    r_stat = await engine._rpc_computer_get_resource_status({})
    assert "healthy" in r_stat

    # 3. Window listing and actions
    w_list = await engine._rpc_computer_list_windows({"visible_only": False})
    assert "windows" in w_list

    # Mock window actions
    with patch.object(engine.window_mgr, "focus_window", return_value=True), \
         patch.object(engine.window_mgr, "minimize_window", return_value=True), \
         patch.object(engine.window_mgr, "maximize_window", return_value=True), \
         patch.object(engine.window_mgr, "restore_window", return_value=True), \
         patch.object(engine.window_mgr, "close_window", return_value=True):
        
        f_res = await engine._rpc_computer_focus_window({"handle": 12345})
        assert f_res["success"] is True

        for act in ["minimize", "maximize", "restore", "close"]:
            act_res = await engine._rpc_computer_window_action({"handle": 12345, "action": act})
            assert act_res["success"] is True

    # 4. Elements inspection & action
    with patch.object(engine.element_inspector, "list_elements", return_value=[]), \
         patch.object(engine.element_interactor, "invoke", return_value=MagicMock(success=True, error=None)), \
         patch.object(engine.element_interactor, "set_value", return_value=MagicMock(success=True, error=None)), \
         patch.object(engine.element_interactor, "toggle", return_value=MagicMock(success=True, error=None)), \
         patch.object(engine.element_interactor, "select", return_value=MagicMock(success=True, error=None)):

        ins_res = await engine._rpc_computer_inspect_elements({"handle": 12345})
        assert "elements" in ins_res

        for act in ["invoke", "set_value", "toggle", "select"]:
            res = await engine._rpc_computer_element_action({"handle": 12345, "action": act, "criteria": {"name": "Btn"}})
            assert res["success"] is True

    # 5. Mouse & Keyboard RPCs
    with patch.object(engine.mouse, "click", return_value=True), \
         patch.object(engine.mouse, "move_to"), \
         patch.object(engine.keyboard, "type_text"), \
         patch.object(engine.keyboard, "send_keys"):

        m_res = await engine._rpc_computer_mouse_action({"action": "click", "x": 100, "y": 100})
        assert m_res["success"] is True

        k_res = await engine._rpc_computer_keyboard_action({"text": "hello"})
        assert k_res["success"] is True

    # 6. Capture Screen & OCR
    cap_res = await engine._rpc_computer_capture_screen({})
    assert cap_res["success"] is True
    assert Path(cap_res["image_path"]).exists()

    ocr_res = await engine._rpc_computer_ocr_screen({"image_path": cap_res["image_path"]})
    assert "text" in ocr_res

    # 7. Filesystem RPCs
    f_path = str(tmp_path / "rpc_file.txt")
    w_res = await engine._rpc_computer_write_file({"path": f_path, "content": "test payload"})
    assert w_res["success"] is True

    r_res = await engine._rpc_computer_read_file({"path": f_path})
    assert r_res["success"] is True
    assert r_res["content"] == "test payload"

    l_res = await engine._rpc_computer_list_directory({"directory": str(tmp_path)})
    assert l_res["success"] is True
    assert len(l_res["files"]) > 0

    d_res = await engine._rpc_computer_delete_file({"path": f_path, "to_recycle_bin": False})
    assert d_res["success"] is True

    # 8. Shell Execute RPC
    sh_res = await engine._rpc_computer_shell_execute({"command": f'"{sys.executable}" --version'})
    assert sh_res["success"] is True
    assert sh_res["returncode"] == 0

    # 9. App Discovery & Control RPCs
    apps_res = await engine._rpc_computer_list_apps({})
    assert "apps" in apps_res

    with patch.object(engine.app_launcher, "launch", return_value=(True, 111, 222)), \
         patch.object(engine.app_controller, "close", return_value=True):
        
        la_res = await engine._rpc_computer_launch_app({"app_name": "notepad"})
        assert la_res["success"] is True
        assert la_res["pid"] == 111

        cl_res = await engine._rpc_computer_close_app({"target": "notepad"})
        assert cl_res["success"] is True
