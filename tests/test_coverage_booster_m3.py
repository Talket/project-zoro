"""Targeted coverage tests for Milestone 03 computer control modules."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from zoro.computer.apps.application_registry import ApplicationRegistry
from zoro.computer.ui.models import WindowInfo, WindowRectangle
from zoro.computer.ui.window_manager import WindowManager
from zoro.computer.vision.capture import ScreenCaptureManager
from zoro.computer.vision.models import CaptureResult, ScreenRegion
from zoro.computer.vision.ocr import WindowsOCR
from zoro.computer.vision.vision_provider import VisionModelInterface


class TestWindowManagerCoverage:
    def test_get_active_window(self):
        mgr = WindowManager()
        with patch("win32gui.GetForegroundWindow", return_value=12345), \
             patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.GetWindowText", return_value="Active Test Window"), \
             patch("win32gui.GetClassName", return_value="ActiveWindowClass"), \
             patch("win32gui.GetWindowRect", return_value=(100, 100, 900, 700)), \
             patch("win32process.GetWindowThreadProcessId", return_value=(0, 4444)), \
             patch("psutil.Process") as mock_proc, \
             patch.object(mgr, "is_hung", return_value=False):

            mock_proc.return_value.name.return_value = "active_app.exe"
            win = mgr.get_active_window()
            assert win is not None
            assert win.handle == 12345
            assert win.title == "Active Test Window"
            assert win.process_name == "active_app.exe"
            assert win.rect.width == 800

    def test_find_window_by_handle_and_process_and_class(self):
        mgr = WindowManager()
        w1 = WindowInfo(
            handle=10,
            title="Window One",
            class_name="ClassA",
            process_id=100,
            process_name="app_one.exe",
            rect=WindowRectangle(left=0, top=0, width=100, height=100),
        )
        w2 = WindowInfo(
            handle=20,
            title="Window Two",
            class_name="ClassB",
            process_id=200,
            process_name="app_two.exe",
            rect=WindowRectangle(left=0, top=0, width=100, height=100),
        )
        with patch.object(mgr, "list_windows", return_value=[w1, w2]):
            assert mgr.find_window(handle=10) == w1
            assert mgr.find_window(process_name="app_two") == w2
            assert mgr.find_window(class_name="ClassB") == w2
            assert mgr.find_window(title_contains="One") == w1

    def test_window_error_and_non_windows_branches(self):
        mgr = WindowManager()
        mgr.is_windows = False

        assert mgr.list_windows() == []
        assert mgr.get_active_window() is None
        assert mgr.focus_window(123) is False
        assert mgr.minimize_window(123) is False
        assert mgr.maximize_window(123) is False
        assert mgr.restore_window(123) is False
        assert mgr.close_window(123) is False
        assert mgr.move_resize_window(123, 0, 0, 10, 10) is False
        assert mgr.is_hung(123) is False

        mgr.is_windows = True
        with patch("win32gui.IsWindow", return_value=False):
            assert mgr.close_window(123) is True
            assert mgr.move_resize_window(123, 0, 0, 10, 10) is False
            assert mgr.focus_window(123) is False


class TestApplicationRegistryCoverage:
    def test_scan_installed_applications_registry(self):
        reg = ApplicationRegistry()

        # Mock winreg keys
        mock_key = MagicMock()
        mock_app_key = MagicMock()

        with patch("winreg.OpenKey", return_value=mock_key), \
             patch("winreg.QueryInfoKey", return_value=(1, 0, 0)), \
             patch("winreg.EnumKey", return_value="TestAppKey"), \
             patch.object(reg, "_get_reg_value") as mock_val:

            def val_side_effect(key, val_name):
                if val_name == "DisplayName":
                    return "Mocked Test Suite App"
                elif val_name == "DisplayVersion":
                    return "1.0.0"
                elif val_name == "Publisher":
                    return "Mocked Corp"
                elif val_name == "DisplayIcon":
                    return r"C:\Test\test_app.exe,0"
                return None

            mock_val.side_effect = val_side_effect

            apps = reg.scan_installed_applications(force_refresh=True)
            assert len(apps) > len(reg._apps) or any(a.display_name == "Mocked Test Suite App" for a in apps)


class TestScreenCaptureAndOCRCoverage:
    def test_capture_active_window(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        with patch("win32gui.GetForegroundWindow", return_value=999), \
             patch("win32gui.IsWindow", return_value=True), \
             patch("win32gui.GetWindowRect", return_value=(10, 20, 110, 120)), \
             patch.object(mgr, "capture_region") as mock_cap_reg:

            mock_cap_reg.return_value = CaptureResult(
                image_path=tmp_path / "win.png",
                width=100,
                height=100,
            )
            res = mgr.capture_active_window(handle=999)
            assert res.width == 100

    def test_ocr_error_branches(self, tmp_path: Path):
        ocr = WindowsOCR()
        test_img = tmp_path / "dummy.png"
        test_img.write_bytes(b"PNG...")

        with patch("subprocess.run") as mock_sub:
            mock_sub.return_value = MagicMock(returncode=2, stderr="Engine Error", stdout="")
            res = ocr.recognize(test_img)
            assert res.success is False
            assert "Engine Error" in res.error

    @pytest.mark.asyncio
    async def test_vision_success_path(self, tmp_path: Path):
        vision = VisionModelInterface()
        test_img = tmp_path / "img.png"
        test_img.write_bytes(b"dummy")

        with patch("httpx.AsyncClient.post") as mock_post:
            mock_resp = MagicMock(status_code=200)
            mock_resp.json.return_value = {"response": "A clean desktop window"}
            mock_post.return_value = mock_resp

            desc = await vision.analyze_screen(test_img, prompt="test")
            assert desc == "A clean desktop window"


from zoro.computer.ui.coordinate_fallback import CoordinateFallbackInteractor
from zoro.computer.ui.verification import UIVerificationEngine
from zoro.computer.ui.mouse import MouseController
from zoro.security.job_object import WindowsJobObject
from zoro.config.paths import AppPaths
from zoro.config.settings import ZoroSettings
from zoro.core.engine import ZoroEngine
from zoro.models.exceptions import (
    ModelNotFoundError,
    ModelProviderError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from zoro.models.base import ChatCompletionRequest, ChatMessage
from zoro.models.llama_cpp import LlamaCppProvider
from zoro.models.ollama import OllamaProvider
import httpx
import time


class TestCoordinateFallbackCoverage:
    def test_click_at_bounds_and_verification_failure(self):
        mouse_mock = MagicMock()
        interactor = CoordinateFallbackInteractor(mouse=mouse_mock)
        bounds = WindowRectangle(left=100, top=100, width=200, height=200)

        # 1. Out of bounds (x < left)
        res1 = interactor.click_at(50, 150, expected_bounds=bounds)
        assert res1.success is False
        assert "out of expected bounds" in res1.error

        # 2. Out of bounds (x > right)
        res2 = interactor.click_at(350, 150, expected_bounds=bounds)
        assert res2.success is False

        # 3. Out of bounds (y < top)
        res3 = interactor.click_at(150, 50, expected_bounds=bounds)
        assert res3.success is False

        # 4. Out of bounds (y > bottom)
        res4 = interactor.click_at(150, 350, expected_bounds=bounds)
        assert res4.success is False

        # 5. Fresh screen verification returns False
        res5 = interactor.click_at(150, 150, expected_bounds=bounds, verify_fresh_screen=lambda: False)
        assert res5.success is False
        assert "pre-action verification" in res5.error.lower()

        # 6. Valid click
        mouse_mock.click.return_value = True
        res6 = interactor.click_at(150, 150, expected_bounds=bounds, verify_fresh_screen=lambda: True)
        assert res6.success is True

    def test_execute_coordinate_action_all_branches(self):
        mouse_mock = MagicMock()
        mouse_mock.click.return_value = True
        mouse_mock.double_click.return_value = True
        mouse_mock.right_click.return_value = True
        mouse_mock.move_to.return_value = True
        interactor = CoordinateFallbackInteractor(mouse=mouse_mock)

        # Negative coords
        assert interactor.execute_coordinate_action(-1, 10) is False
        assert interactor.execute_coordinate_action(10, -5) is False

        # Exceed screen bounds
        assert interactor.execute_coordinate_action(1920, 500, screen_bounds=(1920, 1080)) is False
        assert interactor.execute_coordinate_action(500, 1080, screen_bounds=(1920, 1080)) is False

        # Pre-verify callback failure
        assert interactor.execute_coordinate_action(100, 100, pre_verify_callback=lambda: False) is False

        # Supported actions
        assert interactor.execute_coordinate_action(100, 100, action="click") is True
        assert interactor.execute_coordinate_action(100, 100, action="double_click") is True
        assert interactor.execute_coordinate_action(100, 100, action="right_click") is True
        assert interactor.execute_coordinate_action(100, 100, action="move") is True

        # Unsupported action
        assert interactor.execute_coordinate_action(100, 100, action="unsupported_fly") is False


class TestCaptureManagerDetailedCoverage:
    def test_list_monitors_exception(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        with patch("mss.mss", side_effect=Exception("Driver failure")):
            monitors = mgr.list_monitors()
            assert monitors == []

    def test_capture_full_desktop_monitor_out_of_range(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        res = mgr.capture_full_desktop(monitor_idx=999)
        assert res.image_path.exists()

    def test_capture_active_window_invalid_handle(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        with patch("win32gui.IsWindow", return_value=False):
            with pytest.raises(ValueError, match="Invalid window handle"):
                mgr.capture_active_window(handle=9999999)

    def test_cleanup_old_screenshots(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        f1 = tmp_path / "old.png"
        f1.write_bytes(b"data1")
        f2 = tmp_path / "new.png"
        f2.write_bytes(b"data2")

        # Set f1 mtime to 2000 seconds ago
        past_time = time.time() - 2000
        os.utime(f1, (past_time, past_time))

        deleted = mgr.cleanup_old_screenshots(max_age_seconds=1000)
        assert deleted == 1
        assert not f1.exists()
        assert f2.exists()

        # Exception path during unlink
        f3 = tmp_path / "error.png"
        f3.write_bytes(b"data3")
        os.utime(f3, (past_time, past_time))
        with patch.object(Path, "unlink", side_effect=OSError("Access denied")):
            assert mgr.cleanup_old_screenshots(max_age_seconds=1000) == 0


class TestJobObjectDetailedCoverage:
    def test_job_object_non_windows_branches(self):
        job = WindowsJobObject(name="TestNonWindowsJob")
        job._is_windows = False

        assert job.create() is True
        assert job.assign_process(1234) is True
        assert job.terminate_all() is True
        assert job.query_limit_flags() is None
        assert job.is_handle_inheritable() is False
        assert job.query_active_process_count() == 0

    def test_job_object_open_and_terminate_named_corner_cases(self):
        assert WindowsJobObject.open_existing(None) is None
        assert WindowsJobObject.open_existing("ZoroTestNonExistentJob999") is None
        assert WindowsJobObject.terminate_named_job(None) is False
        assert WindowsJobObject.terminate_named_job("ZoroTestNonExistentJob999") is False

    def test_job_object_assign_process_failure(self):
        job = WindowsJobObject()
        job.handle = 1234
        job._is_windows = True
        with patch("ctypes.WinDLL") as mock_windll:
            mock_kernel = MagicMock()
            mock_kernel.OpenProcess.return_value = 0
            mock_windll.return_value = mock_kernel
            with patch("ctypes.get_last_error", return_value=5):
                assert job.assign_process(99999) is False

    def test_job_object_query_failures(self):
        job = WindowsJobObject()
        job.handle = 1234
        job._is_windows = True
        with patch("ctypes.WinDLL") as mock_windll:
            mock_kernel = MagicMock()
            mock_kernel.QueryInformationJobObject.return_value = 0
            mock_kernel.GetHandleInformation.return_value = 0
            mock_windll.return_value = mock_kernel
            with patch("ctypes.get_last_error", return_value=6):
                assert job.query_limit_flags() is None
                assert job.is_handle_inheritable() is False
                assert job.query_active_process_count() == 0


class TestAppPathsDetailedCoverage:
    def test_paths_custom_env_and_security_fallback(self, tmp_path: Path):
        custom_data = tmp_path / "env_data"
        custom_sec = tmp_path / "env_sec"

        with patch.dict(os.environ, {"ZORO_DATA_DIR": str(custom_data), "ZORO_SECURITY_DIR": str(custom_sec)}):
            p = AppPaths()
            assert p.data_dir == custom_data.resolve()
            assert p.security_dir == custom_sec.resolve()

        # Permission error on security_dir creation
        p_fallback = AppPaths(custom_data_dir=tmp_path / "fb_data")
        orig_mkdir = Path.mkdir
        def mkdir_mock(self, *args, **kwargs):
            if "Security" in str(self):
                raise PermissionError("Access denied")
            return orig_mkdir(self, *args, **kwargs)

        with patch.object(Path, "mkdir", new=mkdir_mock):
            p_fallback.ensure_directories()
            assert p_fallback.security_dir == p_fallback.data_dir / "security"


class TestModelProvidersErrorCoverage:
    @pytest.mark.asyncio
    async def test_ollama_provider_errors(self):
        provider = OllamaProvider()

        # list_models errors
        with patch.object(provider, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.side_effect = httpx.ConnectError("offline")
            mock_gc.return_value = mock_client

            with pytest.raises(ProviderUnavailableError):
                await provider.list_models()

            mock_client.get.side_effect = httpx.TimeoutException("timeout")
            with pytest.raises(ProviderTimeoutError):
                await provider.list_models()

        # get_capabilities errors
        with patch.object(provider, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_gc.return_value = mock_client

            mock_client.post.return_value = MagicMock(status_code=404)
            with pytest.raises(ModelNotFoundError):
                await provider.get_capabilities("non_existent_model")

            mock_client.post.return_value = MagicMock(status_code=500)
            with pytest.raises(ModelProviderError):
                await provider.get_capabilities("error_model")

        # chat_completion errors
        req = ChatCompletionRequest(
            model="mistral",
            messages=[ChatMessage(role="user", content="hello")]
        )
        with patch.object(provider, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_gc.return_value = mock_client

            mock_client.post.side_effect = httpx.ConnectError("offline")
            with pytest.raises(ProviderUnavailableError):
                await provider.chat_completion(req)

            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            with pytest.raises(ProviderTimeoutError):
                await provider.chat_completion(req)

    @pytest.mark.asyncio
    async def test_llama_cpp_provider_errors(self):
        provider = LlamaCppProvider()

        # list_models errors
        with patch.object(provider, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_gc.return_value = mock_client

            mock_client.get.return_value = MagicMock(status_code=500)
            with pytest.raises(ProviderUnavailableError):
                await provider.list_models()

            mock_client.get.side_effect = httpx.ConnectError("offline")
            with pytest.raises(ProviderUnavailableError):
                await provider.list_models()

            mock_client.get.side_effect = httpx.TimeoutException("timeout")
            with pytest.raises(ProviderTimeoutError):
                await provider.list_models()

        # chat_completion errors
        req = ChatCompletionRequest(
            model="default",
            messages=[ChatMessage(role="user", content="hello")]
        )
        with patch.object(provider, "_get_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_gc.return_value = mock_client

            mock_client.post.side_effect = httpx.ConnectError("offline")
            with pytest.raises(ProviderUnavailableError):
                await provider.chat_completion(req)

            mock_client.post.side_effect = httpx.TimeoutException("timeout")
            with pytest.raises(ProviderTimeoutError):
                await provider.chat_completion(req)


class TestEngineRPCExtraCoverage:
    @pytest.mark.asyncio
    async def test_extra_engine_rpcs(self, tmp_path: Path):
        settings = ZoroSettings(
            data_dir=tmp_path,
            pipe_name=rf"\\.\pipe\test-rpc-extra-{tmp_path.name}",
            db_path=tmp_path / "engine_extra.db",
            security_dir=tmp_path / "sec",
            audit_checkpoint_path=tmp_path / "sec" / "audit.checkpoint",
            halt_lock_path=tmp_path / "sec" / "halt.lock",
            pid_path=tmp_path / "sec" / "zoro.pid",
        )
        (tmp_path / "sec").mkdir(parents=True, exist_ok=True)
        engine = ZoroEngine(settings=settings)
        await engine.initialize()

        try:
            # 1. AI Get Benchmarks
            bms = await engine._rpc_ai_get_benchmarks({"limit": 5})
            assert "benchmarks" in bms

            # 2. Window focus with title lookup
            with patch.object(engine.window_mgr, "find_window", return_value=WindowInfo(
                handle=111, title="TestWin", class_name="C", process_id=1, process_name="p",
                rect=WindowRectangle(left=0, top=0, width=10, height=10)
            )), patch.object(engine.window_mgr, "focus_window", return_value=True):
                f_res = await engine._rpc_computer_focus_window({"title": "TestWin"})
                assert f_res["success"] is True

            # Missing handle and title
            f_bad = await engine._rpc_computer_focus_window({})
            assert f_bad["success"] is False

            # 3. Window action errors
            wa_nohwnd = await engine._rpc_computer_window_action({})
            assert wa_nohwnd["success"] is False
            wa_badact = await engine._rpc_computer_window_action({"handle": 111, "action": "explode"})
            assert wa_badact["success"] is False

            # 4. Element inspect missing handle
            ei_nohwnd = await engine._rpc_computer_inspect_elements({})
            assert ei_nohwnd["success"] is False

            # 5. Element action errors
            ea_nohwnd = await engine._rpc_computer_element_action({})
            assert ea_nohwnd["success"] is False
            ea_badact = await engine._rpc_computer_element_action({"handle": 111, "action": "fly"})
            assert ea_badact["success"] is False

            # Element action policy blocked (Profile A Read Only blocks invoke)
            await engine._rpc_computer_set_profile({"profile": "PROFILE_A_READ_ONLY"})
            ea_blocked = await engine._rpc_computer_element_action({"handle": 111, "action": "invoke"})
            assert ea_blocked["success"] is False

            # Reset profile to Standard
            await engine._rpc_computer_set_profile({"profile": "PROFILE_B_STANDARD"})

            # 6. Mouse actions
            with patch.object(engine.mouse, "right_click"), \
                 patch.object(engine.mouse, "double_click"), \
                 patch.object(engine.mouse, "scroll"):
                m_rc = await engine._rpc_computer_mouse_action({"action": "right_click", "x": 10, "y": 10})
                assert m_rc["success"] is True
                m_dc = await engine._rpc_computer_mouse_action({"action": "double_click", "x": 10, "y": 10})
                assert m_dc["success"] is True
                m_sc = await engine._rpc_computer_mouse_action({"action": "scroll", "wheel": -120})
                assert m_sc["success"] is True

            # 7. Keyboard actions
            with patch.object(engine.keyboard, "send_keys"):
                k_keys = await engine._rpc_computer_keyboard_action({"keys": "^c"})
                assert k_keys["success"] is True

            # 8. Capture screen rate limit exceeded
            with patch.object(engine.comp_governor, "check_screenshot_rate", return_value=False):
                cap_blocked = await engine._rpc_computer_capture_screen({})
                assert cap_blocked["success"] is False

            # Capture active window
            with patch.object(engine.capture_mgr, "capture_active_window") as mock_cap_win:
                mock_cap_win.return_value = CaptureResult(
                    image_path=tmp_path / "win.png",
                    width=200,
                    height=200,
                    file_size_bytes=100,
                )
                cap_win = await engine._rpc_computer_capture_screen({"handle": 111})
                assert cap_win["success"] is True

            # 9. OCR screen auto-capture
            with patch.object(engine.capture_mgr, "capture_full_desktop") as mock_cap_full:
                test_img = tmp_path / "ocr_auto.png"
                test_img.write_bytes(b"data")
                mock_cap_full.return_value = CaptureResult(image_path=test_img, width=100, height=100)
                ocr_auto = await engine._rpc_computer_ocr_screen({})
                assert "text" in ocr_auto

            # 10. Filesystem error branches
            ls_err = await engine._rpc_computer_list_directory({"directory": "C:\\NonExistentPathXYZ123"})
            assert ls_err["success"] is False

            rf_bad = await engine._rpc_computer_read_file({})
            assert rf_bad["success"] is False

            wf_bad = await engine._rpc_computer_write_file({})
            assert wf_bad["success"] is False

            df_bad = await engine._rpc_computer_delete_file({})
            assert df_bad["success"] is False

            # Blocked in Profile A
            await engine._rpc_computer_set_profile({"profile": "PROFILE_A_READ_ONLY"})
            wf_blocked = await engine._rpc_computer_write_file({"path": str(tmp_path / "a.txt"), "content": "x"})
            assert wf_blocked["success"] is False
            df_blocked = await engine._rpc_computer_delete_file({"path": str(tmp_path / "a.txt")})
            assert df_blocked["success"] is False

            # 11. Shell execute missing command and blocked tier
            sh_bad = await engine._rpc_computer_shell_execute({})
            assert sh_bad["success"] is False

            # Blocked command (e.g. format C:)
            sh_blocked = await engine._rpc_computer_shell_execute({"command": "format C:"})
            assert sh_blocked["success"] is False

            # 12. App launch / close errors
            la_bad = await engine._rpc_computer_launch_app({})
            assert la_bad["success"] is False

            ca_bad = await engine._rpc_computer_close_app({})
            assert ca_bad["success"] is False

        finally:
            await engine.shutdown()


class TestMouseControllerCoverage:
    def test_mouse_controller_non_windows_and_error_paths(self):
        mc = MouseController()
        mc.is_windows = False

        assert mc.move_to(10, 10) is True
        assert mc.click(10, 10) is True
        assert mc.double_click(10, 10) is True
        assert mc.right_click(10, 10) is True
        assert mc.drag(10, 10, 20, 20) is True
        assert mc.scroll(120) is True

        mc.is_windows = True
        with patch("pywinauto.mouse.move", side_effect=Exception("Move error")), \
             patch("pywinauto.mouse.click", side_effect=Exception("Click error")), \
             patch("pywinauto.mouse.double_click", side_effect=Exception("DClick error")), \
             patch("pywinauto.mouse.right_click", side_effect=Exception("RClick error")), \
             patch("pywinauto.mouse.press", side_effect=Exception("Drag error")), \
             patch("pywinauto.mouse.scroll", side_effect=Exception("Scroll error")):
            assert mc.move_to(10, 10) is False
            assert mc.click(10, 10) is False
            assert mc.double_click(10, 10) is False
            assert mc.right_click(10, 10) is False
            assert mc.drag(10, 10, 20, 20) is False
            assert mc.scroll(120) is False


class TestUIVerificationDetailedCoverage:
    def test_verify_element_methods(self):
        mock_inspector = MagicMock()
        mock_win_mgr = MagicMock()
        engine = UIVerificationEngine(window_mgr=mock_win_mgr, inspector=mock_inspector)

        # 1. verify_window_opened timeout
        mock_win_mgr.find_window.return_value = None
        v_win_fail = engine.verify_window_opened(title="GhostWin", timeout=0.1, poll_interval=0.05)
        assert v_win_fail.verified is False

        # 2. verify_window_closed timeout and success
        mock_win_mgr.list_windows.return_value = [MagicMock(handle=999)]
        v_close_fail = engine.verify_window_closed(handle=999, timeout=0.1, poll_interval=0.05)
        assert v_close_fail.verified is False

        mock_win_mgr.list_windows.return_value = []
        v_close_ok = engine.verify_window_closed(handle=999, timeout=0.1, poll_interval=0.05)
        assert v_close_ok.verified is True

        # 3. verify_element_text success exact and partial, and failure
        mock_elem = MagicMock()
        mock_inspector.find_element.return_value = mock_elem
        mock_info = MagicMock()
        mock_info.name = "Submit Order"
        mock_info.control_type = "Button"
        mock_inspector._extract_element_info.return_value = mock_info

        v_text_ok = engine.verify_element_text(111, {"name": "btn"}, "Submit Order", exact=True, timeout=0.1)
        assert v_text_ok.verified is True

        v_text_part = engine.verify_element_text(111, {"name": "btn"}, "Order", exact=False, timeout=0.1)
        assert v_text_part.verified is True

        v_text_fail = engine.verify_element_text(111, {"name": "btn"}, "Cancel", exact=True, timeout=0.1, poll_interval=0.05)
        assert v_text_fail.verified is False

        # 4. verify_element_exists success and failure
        v_ex_ok = engine.verify_element_exists(111, {"name": "btn"}, timeout=0.1)
        assert v_ex_ok.verified is True

        mock_inspector.find_element.return_value = None
        v_ex_fail = engine.verify_element_exists(111, {"name": "btn"}, timeout=0.1, poll_interval=0.05)
        assert v_ex_fail.verified is False

        # 5. verify_element_vanished success and failure
        v_van_ok = engine.verify_element_vanished(111, {"name": "btn"}, timeout=0.1)
        assert v_van_ok.verified is True

        mock_inspector.find_element.return_value = mock_elem
        v_van_fail = engine.verify_element_vanished(111, {"name": "btn"}, timeout=0.1, poll_interval=0.05)
        assert v_van_fail.verified is False


