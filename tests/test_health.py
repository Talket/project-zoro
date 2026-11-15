"""Tests for hardware telemetry, NVML sampler, and dynamic governor."""

import pytest
from zoro.config.settings import ZoroSettings
from zoro.core.governor import ResourceGovernor
from zoro.core.health import HealthMonitor
from zoro.core.nvml_telemetry import NVMLSampler


def test_health_sampling_structure(test_settings):
    """Verify hardware telemetry structure with real host metrics."""
    monitor = HealthMonitor(settings=test_settings)
    monitor.initialize()

    metrics = monitor.sample_metrics()
    assert "cpu_percent" in metrics
    assert "ram_used_mb" in metrics
    assert "ram_total_mb" in metrics
    assert "disk_free_gb" in metrics
    assert isinstance(metrics["warnings"], list)
    assert metrics["cpu_logical_cores"] > 0
    assert metrics["ram_total_mb"] > 0
    assert metrics["disk_free_gb"] > 0

    monitor.close()


def test_health_sampling_fallback_when_no_gpu(test_settings, monkeypatch):
    """Verify graceful fallback when NVML is unavailable."""
    # Force NVML initialization to fail
    monkeypatch.setattr(NVMLSampler, "initialize", lambda self: False)
    monkeypatch.setattr(NVMLSampler, "sample", lambda self: None)

    monitor = HealthMonitor(settings=test_settings)
    monitor.initialize()

    metrics = monitor.sample_metrics()
    assert metrics["gpu_name"] == "N/A"
    assert metrics["vram_used_mb"] is None
    assert metrics["gpu_temp_c"] is None
    # CPU/RAM must still be sampled properly
    assert metrics["cpu_percent"] >= 0
    assert metrics["ram_used_mb"] > 0

    monitor.close()


def test_health_threshold_warnings(test_settings, monkeypatch):
    """Verify warnings are emitted when resource thresholds are breached."""
    monitor = HealthMonitor(settings=test_settings)
    monitor.initialize()

    # Mock high CPU and VRAM
    monkeypatch.setattr(
        monitor,
        "sample_metrics",
        lambda: {
            "timestamp": 12345.0,
            "cpu_percent": 98.0,
            "cpu_logical_cores": 8,
            "ram_used_mb": 15000.0,
            "ram_total_mb": 16384.0,
            "disk_free_gb": 50.0,
            "gpu_name": "Test GPU",
            "vram_used_mb": 3900.0,
            "vram_total_mb": 4096.0,
            "gpu_temp_c": 75.0,
            "warnings": [
                "VRAM threshold exceeded (3900.0 MB > 3600 MB)!",
                "RAM threshold exceeded (15000.0 MB > 13800 MB)!",
                "CPU threshold exceeded (98.0% > 85.0%)!",
            ],
        },
    )

    metrics = monitor.sample_metrics()
    assert len(metrics["warnings"]) == 3
    assert any("VRAM threshold" in w for w in metrics["warnings"])
    assert any("RAM threshold" in w for w in metrics["warnings"])
    assert any("CPU threshold" in w for w in metrics["warnings"])

    monitor.close()


@pytest.mark.asyncio
async def test_governor_acquire_and_release_workload(test_settings):
    """Verify governor admits workload when under ceiling and releases correctly."""
    monitor = HealthMonitor(settings=test_settings)
    monitor.initialize()
    governor = ResourceGovernor(monitor, settings=test_settings)

    acquired = await governor.acquire_gpu_workload()
    assert acquired is True
    assert governor._is_model_loaded is True

    governor.release_gpu_workload()
    monitor.close()


@pytest.mark.asyncio
async def test_governor_vram_ceiling_rejection(test_settings, monkeypatch):
    """Verify governor blocks new GPU tasks when VRAM usage exceeds ceiling."""
    monitor = HealthMonitor(settings=test_settings)
    monitor.initialize()

    # Simulate VRAM above ceiling (3800 MB > 3600 MB)
    monkeypatch.setattr(
        monitor,
        "sample_metrics",
        lambda: {
            "vram_used_mb": 3800.0,
            "vram_total_mb": 4096.0,
        },
    )

    governor = ResourceGovernor(monitor, settings=test_settings)
    acquired = await governor.acquire_gpu_workload()
    assert acquired is False  # Refused due to VRAM ceiling!

    monitor.close()


def test_governor_idle_eviction_trigger(test_settings):
    """Verify governor triggers eviction callback when idle timeout elapses."""
    monitor = HealthMonitor(settings=test_settings)
    governor = ResourceGovernor(monitor, settings=test_settings)

    evicted = False

    def on_evict():
        nonlocal evicted
        evicted = True

    governor.register_eviction_callback(on_evict)
    governor.record_inference_activity()
    assert governor._is_model_loaded is True

    # Simulate passage of time past idle timeout
    governor._last_inference_time -= (test_settings.model_idle_timeout_sec + 50)
    result = governor.check_idle_eviction()
    assert result is True
    assert evicted is True
    assert governor._is_model_loaded is False
