"""Resource Governor for PROJECT ZORO.

Enforces execution rate limits, task concurrency ceilings, and system health
thresholds (CPU and memory utilization) to prevent resource starvation or system freezing.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Optional

import psutil

from zoro.computer.sandbox.models import ResourceLimits

logger = logging.getLogger(__name__)


class ResourceGovernor:
    """Monitors and governs resource consumption during computer control operations."""

    def __init__(self, limits: Optional[ResourceLimits] = None) -> None:
        self.limits = limits or ResourceLimits()
        self._screenshot_timestamps: deque[float] = deque()
        self._lock = threading.Lock()
        self._active_tasks = 0

    def check_screenshot_rate(self) -> bool:
        """Checks if a new screenshot can be captured under rate limits."""
        now = time.time()
        window_start = now - 60.0

        with self._lock:
            # Purge timestamps older than 60s
            while self._screenshot_timestamps and self._screenshot_timestamps[0] < window_start:
                self._screenshot_timestamps.popleft()

            if len(self._screenshot_timestamps) >= self.limits.max_screenshots_per_minute:
                logger.warning("Screenshot rate limit exceeded (%d/min)", self.limits.max_screenshots_per_minute)
                return False

            return True

    def record_screenshot(self) -> None:
        """Records a captured screenshot timestamp."""
        with self._lock:
            self._screenshot_timestamps.append(time.time())

    def acquire_task_slot(self) -> bool:
        """Attempts to acquire a task execution slot."""
        with self._lock:
            if self._active_tasks >= self.limits.max_concurrent_tasks:
                logger.warning("Max concurrent tasks ceiling reached (%d)", self.limits.max_concurrent_tasks)
                return False
            self._active_tasks += 1
            return True

    def release_task_slot(self) -> None:
        """Releases an active task execution slot."""
        with self._lock:
            if self._active_tasks > 0:
                self._active_tasks -= 1

    @property
    def active_tasks_count(self) -> int:
        with self._lock:
            return self._active_tasks

    def check_system_health(self) -> tuple[bool, str]:
        """Checks CPU and Memory load against safety thresholds."""
        try:
            mem = psutil.virtual_memory()
            used_mb = (mem.total - mem.available) / (1024 * 1024)
            cpu = psutil.cpu_percent(interval=None)

            if cpu > self.limits.max_cpu_percent:
                return False, f"Host CPU usage high ({cpu}% > {self.limits.max_cpu_percent}%)"

            if mem.percent > 92.0:
                return False, f"Host Memory usage critical ({mem.percent}% > 92%)"

            return True, f"System healthy: CPU {cpu}%, RAM {mem.percent}% ({used_mb:.0f} MB)"
        except Exception as e:
            return True, f"System health check bypassed: {e}"
