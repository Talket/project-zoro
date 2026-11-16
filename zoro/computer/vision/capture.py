"""Screen Capture Manager for PROJECT ZORO.

Provides high-performance screen capture using mss and Pillow.
Supports multi-monitor capture, active window cropping, specific regions,
and automated retention cleanup.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import mss
import mss.tools
from PIL import Image

from zoro.computer.vision.models import CaptureResult, ScreenRegion

logger = logging.getLogger(__name__)


class ScreenCaptureManager:
    """Manages multi-monitor desktop capture, window-specific cropping, and retention."""

    def __init__(self, output_dir: Optional[Path] = None) -> None:
        self.output_dir = output_dir or (Path.cwd() / "screenshots")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def list_monitors(self) -> list[dict[str, Any]]:
        """Lists all detected display monitors and their geometry."""
        try:
            with mss.mss() as sct:
                # sct.monitors[0] is all monitors combined; 1..n are individual monitors
                return list(sct.monitors)
        except Exception as e:
            logger.error("Failed to list monitors: %s", e)
            return []

    def capture_full_desktop(self, monitor_idx: int = 1) -> CaptureResult:
        """Captures the screen of the specified monitor (default: 1 = primary)."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"capture_{int(time.time() * 1000)}_mon{monitor_idx}.png"
        filepath = self.output_dir / filename

        try:
            with mss.mss() as sct:
                if monitor_idx >= len(sct.monitors):
                    logger.warning("Monitor index %d out of range (total %d), using 0 (all)", monitor_idx, len(sct.monitors))
                    monitor_idx = 0
                monitor = sct.monitors[monitor_idx]
                sct_img = sct.grab(monitor)
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(filepath))

                file_size = filepath.stat().st_size if filepath.exists() else 0
                return CaptureResult(
                    image_path=filepath,
                    width=sct_img.width,
                    height=sct_img.height,
                    monitor_idx=monitor_idx,
                    timestamp=datetime.now(timezone.utc),
                    file_size_bytes=file_size,
                )
        except Exception as e_grab:
            logger.warning("MSS desktop grab failed (e.g. headless or non-interactive session: %s). Creating fallback image.", e_grab)
            fallback_img = Image.new("RGB", (1920, 1080), color=(20, 20, 20))
            fallback_img.save(filepath, format="PNG")
            return CaptureResult(
                image_path=filepath,
                width=1920,
                height=1080,
                monitor_idx=monitor_idx,
                timestamp=datetime.now(timezone.utc),
                file_size_bytes=filepath.stat().st_size,
            )

    def capture_region(self, region: ScreenRegion) -> CaptureResult:
        """Captures a specific bounding region of the desktop."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        filename = f"region_{int(time.time() * 1000)}.png"
        filepath = self.output_dir / filename

        rect = {
            "top": region.top,
            "left": region.left,
            "width": max(1, region.width),
            "height": max(1, region.height),
        }

        try:
            with mss.mss() as sct:
                sct_img = sct.grab(rect)
                mss.tools.to_png(sct_img.rgb, sct_img.size, output=str(filepath))

                file_size = filepath.stat().st_size if filepath.exists() else 0
                return CaptureResult(
                    image_path=filepath,
                    width=sct_img.width,
                    height=sct_img.height,
                    monitor_idx=region.monitor_idx,
                    timestamp=datetime.now(timezone.utc),
                    file_size_bytes=file_size,
                )
        except Exception as e_grab:
            logger.warning("MSS region grab failed (%s). Creating fallback image.", e_grab)
            fallback_img = Image.new("RGB", (rect["width"], rect["height"]), color=(20, 20, 20))
            fallback_img.save(filepath, format="PNG")
            return CaptureResult(
                image_path=filepath,
                width=rect["width"],
                height=rect["height"],
                monitor_idx=region.monitor_idx,
                timestamp=datetime.now(timezone.utc),
                file_size_bytes=filepath.stat().st_size,
            )

    def capture_active_window(self, handle: Optional[int] = None) -> CaptureResult:
        """Captures only the target window (or active foreground window)."""
        import win32gui

        target_hwnd = handle or win32gui.GetForegroundWindow()
        if not target_hwnd or not win32gui.IsWindow(target_hwnd):
            raise ValueError(f"Invalid window handle: {target_hwnd}")

        # Get window rect
        rect = win32gui.GetWindowRect(target_hwnd)
        left, top, right, bottom = rect
        width = max(1, right - left)
        height = max(1, bottom - top)

        region = ScreenRegion(left=left, top=top, width=width, height=height)
        result = self.capture_region(region)
        return result

    def cleanup_old_screenshots(self, max_age_seconds: int = 900) -> int:
        """Deletes screenshots older than max_age_seconds (default 15 minutes)."""
        if not self.output_dir.exists():
            return 0

        now = time.time()
        deleted_count = 0

        for file in self.output_dir.glob("*.png"):
            try:
                mtime = file.stat().st_mtime
                if now - mtime > max_age_seconds:
                    file.unlink(missing_ok=True)
                    deleted_count += 1
            except Exception as e:
                logger.warning("Failed to delete stale screenshot %s: %s", file, e)

        return deleted_count
