"""End-to-End integration tests for Windows Computer Control via Named Pipe IPC in PROJECT ZORO."""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path
import pytest

from zoro.config.settings import ZoroSettings
from zoro.core.engine import ZoroEngine
from zoro.ipc.pipe_client import NamedPipeClient


@pytest.fixture
async def computer_engine_system(tmp_path: Path):
    pipe_id = uuid.uuid4().hex[:8]
    pipe_name = rf"\\.\pipe\zoro-test-computer-{pipe_id}"
    sec_dir = tmp_path / "security"
    sec_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "zoro_computer_e2e.db"

    settings = ZoroSettings(
        data_dir=tmp_path,
        pipe_name=pipe_name,
        db_path=db_path,
        security_dir=sec_dir,
        audit_checkpoint_path=sec_dir / "audit.checkpoint",
        halt_lock_path=sec_dir / "halt.lock",
        pid_path=sec_dir / "zoro.pid",
    )

    engine = ZoroEngine(settings=settings)
    await engine.initialize()

    client = NamedPipeClient(pipe_name=pipe_name, settings=settings)
    connected = False
    for _ in range(25):
        if client.connect():
            connected = True
            break
        await asyncio.sleep(0.1)

    assert connected is True, "NamedPipeClient failed to connect to ZoroEngine"

    yield engine, client, tmp_path

    client.close()
    await engine.shutdown()


@pytest.mark.asyncio
async def test_computer_control_ipc_full_lifecycle(computer_engine_system):
    engine, client, tmp_path = computer_engine_system

    async def send_req(method: str, params: dict | None = None) -> dict:
        return await asyncio.to_thread(client.send_request, method, params or {})

    # 1. Get and Set Profile
    prof_res = await send_req("computer.get_profile")
    assert prof_res is not None
    assert prof_res.get("profile") == "PROFILE_B_STANDARD"

    set_prof = await send_req("computer.set_profile", {"profile": "PROFILE_C_RESTRICTED_MODIFICATION"})
    assert set_prof.get("success") is True
    assert set_prof.get("profile") == "PROFILE_C_RESTRICTED_MODIFICATION"

    # 2. Resource status
    status = await send_req("computer.get_resource_status")
    assert status.get("healthy") is True

    # 3. List Windows
    win_res = await send_req("computer.list_windows", {"visible_only": False})
    assert "windows" in win_res
    assert isinstance(win_res["windows"], list)

    # 4. Screen Capture
    cap_res = await send_req("computer.capture_screen")
    assert cap_res.get("success") is True
    assert Path(cap_res.get("image_path")).exists()

    # 5. Filesystem Operations
    test_file = tmp_path / "ipc_test.txt"
    w_res = await send_req("computer.write_file", {"path": str(test_file), "content": "ZORO IPC FS TEST"})
    assert w_res.get("success") is True

    r_res = await send_req("computer.read_file", {"path": str(test_file)})
    assert r_res.get("success") is True
    assert r_res.get("content") == "ZORO IPC FS TEST"

    del_res = await send_req("computer.delete_file", {"path": str(test_file), "to_recycle_bin": False})
    assert del_res.get("success") is True
    assert not test_file.exists()

    # 6. Shell Execution
    sh_res = await send_req("computer.shell_execute", {"command": f'"{sys.executable}" --version'})
    assert sh_res.get("success") is True
    assert sh_res.get("returncode") == 0
    assert "Python" in sh_res.get("stdout") or "Python" in sh_res.get("stderr")

    # 7. List Apps
    apps_res = await send_req("computer.list_apps")
    assert "apps" in apps_res
    assert len(apps_res["apps"]) > 0
    app_names = [a.get("name") for a in apps_res["apps"]]
    assert "notepad" in app_names
