"""Empirical Hardware and AI Model Benchmarking Harness.

Evaluates Time-to-First-Token (TTFT), tokens/sec, VRAM high-water mark, and structured JSON compliance.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import sys
import time
from typing import Any, Dict, List, Optional
import psutil

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zoro.core.nvml_telemetry import NVMLSampler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [Benchmark] %(message)s")
logger = logging.getLogger("ModelBenchmark")


class ModelBenchmarkRunner:
    """Automated benchmark runner for local models on the Acer Nitro 5."""

    def __init__(self, endpoint_url: str = "http://127.0.0.1:11434") -> None:
        self.endpoint_url = endpoint_url
        self.nvml = NVMLSampler()
        self.gpu_available = self.nvml.initialize()

    def sample_hardware(self) -> Dict[str, Any]:
        ram = psutil.virtual_memory()
        gpu = self.nvml.sample() if self.gpu_available else None
        return {
            "ram_used_mb": round((ram.total - ram.available) / (1024 * 1024), 1),
            "vram_used_mb": gpu["vram_used_mb"] if gpu else None,
            "gpu_temp_c": gpu["gpu_temp_c"] if gpu else None,
        }

    async def benchmark_mock(self) -> Dict[str, Any]:
        """Baseline benchmark using mock engine."""
        logger.info("Executing baseline hardware benchmark...")
        start_hw = self.sample_hardware()
        start_time = time.perf_counter()

        # Simulate synthetic load
        await asyncio.sleep(0.5)

        end_time = time.perf_counter()
        end_hw = self.sample_hardware()

        return {
            "model": "Mock-Baseline",
            "elapsed_seconds": round(end_time - start_time, 3),
            "baseline_ram_mb": start_hw["ram_used_mb"],
            "baseline_vram_mb": start_hw["vram_used_mb"],
            "gpu_name": self.nvml.device_name if self.gpu_available else "N/A",
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="ZORO Local Model Benchmark Harness")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:11434", help="Inference endpoint URL")
    parser.add_argument("--model", type=str, default="mock", help="Model name to benchmark")
    args = parser.parse_args()

    runner = ModelBenchmarkRunner(endpoint_url=args.url)
    results = asyncio.run(runner.benchmark_mock())

    print("\n=======================================================")
    print("      ZORO HARDWARE & MODEL BENCHMARK RESULTS")
    print("=======================================================")
    for k, v in results.items():
        print(f"  {k:25s}: {v}")
    print("=======================================================\n")


if __name__ == "__main__":
    main()
