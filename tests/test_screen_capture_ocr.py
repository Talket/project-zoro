"""Tests for Screen Capture & WinRT OCR Perception in PROJECT ZORO."""

from __future__ import annotations

import time
from pathlib import Path
from PIL import Image, ImageDraw
import pytest

from zoro.computer.vision.capture import ScreenCaptureManager
from zoro.computer.vision.models import CaptureResult, OCRResult, ScreenRegion
from zoro.computer.vision.ocr import WindowsOCR
from zoro.computer.vision.vision_provider import VisionModelInterface


class TestScreenCaptureManager:
    def test_list_monitors(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        monitors = mgr.list_monitors()
        assert isinstance(monitors, list)
        assert len(monitors) > 0

    def test_capture_full_desktop(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        res = mgr.capture_full_desktop(monitor_idx=1)
        assert isinstance(res, CaptureResult)
        assert res.image_path.exists()
        assert res.width > 0
        assert res.height > 0
        assert res.file_size_bytes > 0

    def test_capture_region(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        region = ScreenRegion(left=10, top=10, width=100, height=80)
        res = mgr.capture_region(region)
        assert res.image_path.exists()
        assert res.width == 100
        assert res.height == 80

    def test_cleanup_old_screenshots(self, tmp_path: Path):
        mgr = ScreenCaptureManager(output_dir=tmp_path)
        # Create dummy old file
        old_file = tmp_path / "capture_old.png"
        old_file.write_text("dummy")
        # Set mtime to 1000s ago
        old_mtime = time.time() - 1000
        import os
        os.utime(str(old_file), (old_mtime, old_mtime))

        new_file = tmp_path / "capture_new.png"
        new_file.write_text("dummy")

        deleted = mgr.cleanup_old_screenshots(max_age_seconds=500)
        assert deleted == 1
        assert not old_file.exists()
        assert new_file.exists()


class TestWindowsOCR:
    def test_recognize_text_from_image(self, tmp_path: Path):
        img_path = tmp_path / "test_ocr.png"
        img = Image.new("RGB", (400, 100), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((20, 30), "ZORO PROJECT AUTOMATION", fill=(0, 0, 0))
        img.save(img_path)

        ocr = WindowsOCR()
        res = ocr.recognize(img_path)
        assert isinstance(res, OCRResult)
        assert res.success is True
        assert "ZORO" in res.full_text.upper() or len(res.words) > 0

    def test_recognize_missing_file(self, tmp_path: Path):
        missing = tmp_path / "does_not_exist.png"
        ocr = WindowsOCR()
        res = ocr.recognize(missing)
        assert res.success is False
        assert "not found" in res.error.lower()


class TestVisionModelInterface:
    @pytest.mark.asyncio
    async def test_vision_fallback_to_ocr(self, tmp_path: Path):
        img_path = tmp_path / "vision_test.png"
        img = Image.new("RGB", (300, 80), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.text((10, 20), "STATUS OK", fill=(0, 0, 0))
        img.save(img_path)

        # Non-existent endpoint forces fallback to OCR
        vision = VisionModelInterface(
            endpoint_url="http://127.0.0.1:99999/api/generate",
            model_name="llava:7b",
        )
        res_text = await vision.analyze_screen(img_path, prompt="Describe what you see")
        assert isinstance(res_text, str)
        assert len(res_text) > 0
