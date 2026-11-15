"""Host health, system metrics, and hardware telemetry sampler."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional
import psutil

from zoro.config.settings import ZoroSettings, get_settings
from zoro.core.nvml_telemetry import NVMLSampler

logger = logging.getLogger(__name__)


class HealthMonitor:
    """Samples host hardware and system performance metrics."""

    def __init__(self, settings: Optional[ZoroSettings] = None) -> None:
        self.settings = settings or get_settings()
        self.nvml = NVMLSampler()
        self._gpu_supported = False

    def initialize(self) -> None:
        """Initialize NVML and background telemetry handles."""
        self._gpu_supported = self.nvml.initialize()

    def sample_metrics(self) -> Dict[str, Any]:
        """Collect a full snapshot of system and hardware metrics."""
        # CPU
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)

        # RAM
        ram = psutil.virtual_memory()
        ram_used_mb = round((ram.total - ram.available) / (1024 * 1024), 1)
        ram_total_mb = round(ram.total / (1024 * 1024), 1)
        ram_percent = ram.percent

        # Disk Free on primary project drive
        try:
            disk = psutil.disk_usage("D:\\" if os.path.exists("D:\\") else "C:\\")
            disk_free_gb = round(disk.free / (1024 * 1024 * 1024), 1)
        except Exception:
            disk_free_gb = 0.0

        # GPU via direct NVML
        gpu_metrics = self.nvml.sample() if self._gpu_supported else None

        metrics: Dict[str, Any] = {
            "timestamp": time.time(),
            "cpu_percent": cpu_percent,
            "cpu_logical_cores": cpu_count,
            "ram_used_mb": ram_used_mb,
            "ram_total_mb": ram_total_mb,
            "ram_percent": ram_percent,
            "disk_free_gb": disk_free_gb,
            "gpu_name": self.nvml.device_name if self._gpu_supported else "N/A",
            "vram_used_mb": gpu_metrics["vram_used_mb"] if gpu_metrics else None,
            "vram_total_mb": gpu_metrics["vram_total_mb"] if gpu_metrics else None,
            "gpu_temp_c": gpu_metrics["gpu_temp_c"] if gpu_metrics else None,
            "gpu_utilization_percent": gpu_metrics["gpu_utilization_percent"] if gpu_metrics else None,
        }

        # Check threshold warnings
        warnings: List[str] = []
        if gpu_metrics and gpu_metrics["vram_used_mb"] > self.settings.max_vram_mb:
            warnings.append(f"VRAM threshold exceeded ({gpu_metrics['vram_used_mb']} MB > {self.settings.max_vram_mb} MB)!")
        if ram_used_mb > self.settings.max_ram_mb:
            warnings.append(f"RAM threshold exceeded ({ram_used_mb} MB > {self.settings.max_ram_mb} MB)!")
        if cpu_percent > self.settings.max_cpu_percent:
            warnings.append(f"CPU threshold exceeded ({cpu_percent}% > {self.settings.max_cpu_percent}%)!")

        metrics["warnings"] = warnings
        return metrics

    def close(self) -> None:
        """Cleanly close telemetry resources."""
        self.nvml.shutdown()
