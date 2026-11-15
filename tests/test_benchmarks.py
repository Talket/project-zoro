"""Tests for Hardware-Aware Local AI Model Benchmarking."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.benchmarks.runner import HardwareAwareBenchmarkRunner, BenchmarkMetric
from zoro.models.base import ChatCompletionResponse
from zoro.models.mock import MockModelProvider
from zoro.models.registry import ProviderRegistry
from zoro.storage.db import DatabaseManager


@pytest.mark.asyncio
async def test_sample_hardware_and_runtimes():
    runner = HardwareAwareBenchmarkRunner()
    hw = runner.sample_hardware()
    assert "ram_used_mb" in hw
    assert "ram_total_mb" in hw
    assert hw["ram_total_mb"] > 0

    status = await runner.detect_available_runtimes()
    assert isinstance(status, dict)
    assert "mock" in status


@pytest.mark.asyncio
async def test_run_benchmark_with_mock_and_db(tmp_path):
    db_path = tmp_path / "benchmarks.db"
    db = DatabaseManager(db_path=db_path)
    await db.initialize()

    registry = ProviderRegistry()
    mock_provider = MockModelProvider(default_response="RED, GREEN, BLUE")
    registry.register_provider("mock", mock_provider, default_model="mock-v1")

    runner = HardwareAwareBenchmarkRunner(registry=registry, db=db)

    # Run benchmark
    metric = await runner.run_benchmark(provider_name="mock", model_name="mock-v1")

    assert metric.model_name == "mock-v1"
    assert metric.provider_id == "mock"
    assert metric.ttft_ms > 0
    assert metric.tokens_per_sec > 0
    assert metric.ram_used_mb > 0
    assert metric.tool_calling_supported is True

    # Check persistence in database
    rows = await db.execute_read(
        "SELECT model_name, provider_id, ttft_ms, tokens_per_sec, instruction_following_score FROM model_benchmarks"
    )
    assert len(rows) == 1
    assert rows[0][0] == "mock-v1"
    assert rows[0][1] == "mock"

    await db.close()


@pytest.mark.asyncio
async def test_benchmark_streaming_fallback(tmp_path):
    db_path = tmp_path / "benchmarks_fallback.db"
    db = DatabaseManager(db_path=db_path)
    await db.initialize()

    registry = ProviderRegistry()
    mock_provider = MockModelProvider(default_response="Single kernel sentence.")
    registry.register_provider("mock", mock_provider, default_model="mock-v1")

    runner = HardwareAwareBenchmarkRunner(registry=registry, db=db)

    # Force streaming to raise an exception to trigger the fallback branch
    with patch.object(mock_provider, "chat_completion_stream", side_effect=RuntimeError("Stream failure")):
        metric = await runner.run_benchmark(provider_name="mock", model_name="mock-v1")
        assert metric.tokens_per_sec > 0
        assert metric.ttft_ms > 0

    await db.close()


@pytest.mark.asyncio
async def test_benchmark_vram_warning():
    runner = HardwareAwareBenchmarkRunner()
    with patch.object(runner, "sample_hardware", return_value={
        "ram_used_mb": 4096.0,
        "ram_total_mb": 16384.0,
        "vram_used_mb": 3800.0,
        "vram_total_mb": 4096.0,
        "gpu_temp_c": 75.0,
        "gpu_name": "NVIDIA GeForce GTX 1050 Ti"
    }):
        registry = ProviderRegistry()
        mock_provider = MockModelProvider()
        registry.register_provider("mock", mock_provider)
        runner.registry = registry

        metric = await runner.run_benchmark(provider_name="mock", model_name="mock-v1")
        assert "WARNING: VRAM usage exceeds 3.5 GB" in metric.hardware_notes
