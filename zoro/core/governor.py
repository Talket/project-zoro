"""Dynamic hardware resource governor and workload serialization controller."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional

from zoro.config.settings import ZoroSettings, get_settings
from zoro.core.health import HealthMonitor

logger = logging.getLogger(__name__)


class ResourceGovernor:
    """Governs hardware utilization, serializes GPU tasks, and prevents memory starvation."""

    def __init__(self, health_monitor: HealthMonitor, settings: Optional[ZoroSettings] = None) -> None:
        self.health = health_monitor
        self.settings = settings or get_settings()
        self._gpu_lock = asyncio.Lock()
        self._last_inference_time = time.time()
        self._is_model_loaded = False
        self._on_evict_callback: Optional[Callable[[], Any]] = None

    def register_eviction_callback(self, callback: Callable[[], Any]) -> None:
        """Register a callback invoked when the governor decides to unload model weights."""
        self._on_evict_callback = callback

    def record_inference_activity(self) -> None:
        """Update timestamp of active inference to reset idle timer."""
        self._last_inference_time = time.time()
        self._is_model_loaded = True

    async def acquire_gpu_workload(self) -> bool:
        """
        Acquire lock for a heavy GPU workload (Single Heavy GPU Workload policy).
        Ensures STT and LLM never contend for GTX 1050 Ti VRAM.
        """
        # 1. Sample current VRAM and evaluate dynamic ceiling
        metrics = self.health.sample_metrics()
        vram_used = metrics.get("vram_used_mb")
        vram_total = metrics.get("vram_total_mb")
        ceiling = self.settings.max_vram_mb
        if vram_total and vram_total > 0:
            ceiling = min(ceiling, int(vram_total * 0.90))

        if vram_used and vram_used > ceiling:
            logger.warning("Governor: Refusing new GPU workload -- VRAM used (%s MB) exceeds limit (%s MB).",
                           vram_used, ceiling)
            return False

        await self._gpu_lock.acquire()
        self.record_inference_activity()
        return True

    def release_gpu_workload(self) -> None:
        """Release GPU workload lock upon completion."""
        if self._gpu_lock.locked():
            self._gpu_lock.release()

    def check_idle_eviction(self) -> bool:
        """
        Check if model has been idle longer than model_idle_timeout_sec.
        If so, trigger model weight eviction from VRAM.
        """
        if not self._is_model_loaded:
            return False

        idle_seconds = time.time() - self._last_inference_time
        if idle_seconds > self.settings.model_idle_timeout_sec:
            logger.info("Governor: Model idle for %.1f seconds. Triggering VRAM eviction.", idle_seconds)
            self._is_model_loaded = False
            if self._on_evict_callback:
                try:
                    self._on_evict_callback()
                except Exception as e:
                    logger.error("Error executing eviction callback: %s", e)
            return True
        return False
