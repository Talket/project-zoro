"""Direct NVIDIA NVML C-bindings via ctypes for low-latency GPU telemetry."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class c_nvmlMemory_t(ctypes.Structure):
    _fields_ = [
        ("total", ctypes.c_ulonglong),
        ("free", ctypes.c_ulonglong),
        ("used", ctypes.c_ulonglong),
    ]


class c_nvmlUtilization_t(ctypes.Structure):
    _fields_ = [
        ("gpu", ctypes.c_uint),
        ("memory", ctypes.c_uint),
    ]


class NVMLSampler:
    """Samples NVIDIA GPU telemetry directly through nvml.dll."""

    def __init__(self) -> None:
        self._nvml: Optional[ctypes.CDLL] = None
        self._device_handle = None
        self._initialized = False
        self.device_name: str = "Unknown GPU"

    def initialize(self) -> bool:
        """Load nvml.dll and initialize the primary device handle."""
        if self._initialized:
            return True

        try:
            self._nvml = ctypes.CDLL("nvml.dll")
            ret = self._nvml.nvmlInit_v2()
            if ret != 0:
                logger.warning("nvmlInit_v2 returned error code %d", ret)
                return False

            device_count = ctypes.c_uint()
            self._nvml.nvmlDeviceGetCount_v2(ctypes.byref(device_count))
            if device_count.value == 0:
                logger.warning("No NVML-compatible NVIDIA devices found.")
                return False

            # Get handle for GPU 0 (GTX 1050 Ti)
            self._device_handle = ctypes.c_void_p()
            ret = self._nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self._device_handle))
            if ret != 0:
                logger.warning("Failed to obtain device handle for GPU 0.")
                return False

            # Get name
            name_buf = ctypes.create_string_buffer(64)
            self._nvml.nvmlDeviceGetName(self._device_handle, name_buf, 64)
            self.device_name = name_buf.value.decode("utf-8", errors="ignore")

            self._initialized = True
            logger.info("NVML initialized successfully for GPU: %s", self.device_name)
            return True
        except Exception as e:
            logger.warning("NVML unavailable (%s). GPU telemetry will be mocked or omitted.", e)
            self._initialized = False
            return False

    def sample(self) -> Optional[Dict[str, float]]:
        """
        Sample GPU metrics in <1ms without child processes.
        Returns dict with total_mb, used_mb, free_mb, temp_c, and utilization_percent.
        """
        if not self._initialized or not self._nvml or not self._device_handle:
            return None

        try:
            # Memory Info
            mem = c_nvmlMemory_t()
            ret = self._nvml.nvmlDeviceGetMemoryInfo(self._device_handle, ctypes.byref(mem))
            if ret != 0:
                return None

            # Temperature (NVML_TEMPERATURE_GPU = 0)
            temp = ctypes.c_uint()
            self._nvml.nvmlDeviceGetTemperature(self._device_handle, 0, ctypes.byref(temp))

            # Utilization Rates
            util = c_nvmlUtilization_t()
            self._nvml.nvmlDeviceGetUtilizationRates(self._device_handle, ctypes.byref(util))

            return {
                "vram_total_mb": round(mem.total / (1024 * 1024), 1),
                "vram_used_mb": round(mem.used / (1024 * 1024), 1),
                "vram_free_mb": round(mem.free / (1024 * 1024), 1),
                "gpu_temp_c": float(temp.value),
                "gpu_utilization_percent": float(util.gpu),
            }
        except Exception as e:
            logger.debug("NVML sample error: %s", e)
            return None

    def shutdown(self) -> None:
        """Shutdown NVML session."""
        if self._initialized and self._nvml:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
            self._initialized = False

    def close(self) -> None:
        """Alias for shutdown()."""
        self.shutdown()
