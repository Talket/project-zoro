"""Hardware-Aware Local AI Model Benchmarking Subsystem.

Evaluates Time-to-First-Token (TTFT), tokens/sec, memory/VRAM load,
structured JSON compliance, instruction following, and tool-calling capability.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import psutil

from zoro.core.nvml_telemetry import NVMLSampler
from zoro.models.base import (
    BaseModelProvider,
    ChatCompletionRequest,
    ChatMessage,
    ModelInfo,
)
from zoro.models.llama_cpp import LlamaCppProvider
from zoro.models.mock import MockModelProvider
from zoro.models.ollama import OllamaProvider
from zoro.models.registry import ProviderRegistry
from zoro.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class BenchmarkMetric(BaseModel):
    model_name: str
    provider_id: str
    timestamp: str
    ttft_ms: float
    tokens_per_sec: float
    ram_used_mb: float
    vram_used_mb: Optional[float] = None
    gpu_temp_c: Optional[float] = None
    structured_json_score: float = 0.0
    instruction_following_score: float = 0.0
    tool_calling_supported: bool = False
    hardware_notes: str = ""
    raw_metrics: Dict[str, Any] = Field(default_factory=dict)


class HardwareAwareBenchmarkRunner:
    """Hardware-aware benchmark suite for local AI models running on the host system."""

    def __init__(
        self,
        registry: Optional[ProviderRegistry] = None,
        db: Optional[DatabaseManager] = None,
    ) -> None:
        self.registry = registry or ProviderRegistry()
        self.db = db
        self.nvml = NVMLSampler()
        self.gpu_available = self.nvml.initialize()

    def sample_hardware(self) -> Dict[str, Any]:
        """Capture active host RAM and GPU VRAM telemetry."""
        ram = psutil.virtual_memory()
        gpu = self.nvml.sample() if self.gpu_available else None
        return {
            "ram_used_mb": round((ram.total - ram.available) / (1024 * 1024), 1),
            "ram_total_mb": round(ram.total / (1024 * 1024), 1),
            "vram_used_mb": gpu["vram_used_mb"] if gpu else None,
            "vram_total_mb": gpu["vram_total_mb"] if gpu else None,
            "gpu_temp_c": gpu["gpu_temp_c"] if gpu else None,
            "gpu_name": self.nvml.device_name if self.gpu_available else "N/A",
        }

    async def detect_available_runtimes(self) -> Dict[str, bool]:
        """Probe configured runtimes for active availability."""
        status = {}
        for name in ["mock", "ollama", "llama.cpp"]:
            try:
                provider = self.registry.get_provider(name)
                health = await provider.health_check()
                status[name] = health.is_available
            except Exception:
                status[name] = False
        return status

    async def run_benchmark(
        self,
        provider_name: str,
        model_name: str,
    ) -> BenchmarkMetric:
        """
        Execute comprehensive hardware-aware evaluation:
        1. Latency & Token Throughput (TTFT + tokens/sec)
        2. Structured JSON generation compliance
        3. Multi-constraint instruction following
        4. Tool-calling protocol compatibility
        """
        provider = self.registry.get_provider(provider_name)
        logger.info("Starting benchmark for '%s' via provider '%s'...", model_name, provider_name)

        hw_before = self.sample_hardware()

        # ---------------------------------------------------------
        # Test 1: Latency & Throughput (TTFT + tokens/sec)
        # ---------------------------------------------------------
        test_prompt = "Explain in three concise sentences what an operating system kernel does."
        start_time = time.perf_counter()
        ttft_ms = 0.0
        generated_tokens = 0
        response_text = ""

        try:
            req = ChatCompletionRequest(
                model=model_name,
                messages=[ChatMessage(role="user", content=test_prompt)],
                temperature=0.2,
                max_tokens=256,
                stream=True,
            )

            first_token_received = False
            async for chunk in provider.chat_completion_stream(req):
                if not first_token_received and chunk.delta_content:
                    ttft_ms = round((time.perf_counter() - start_time) * 1000, 2)
                    first_token_received = True
                if chunk.delta_content:
                    response_text += chunk.delta_content
                    # Approximate token count by word splitting (~1.3 tokens/word)
                    generated_tokens += max(1, len(chunk.delta_content.split()))

            total_duration = max(0.001, time.perf_counter() - start_time)
            tokens_per_sec = round(generated_tokens / total_duration, 2)
            if ttft_ms == 0.0:
                ttft_ms = round(total_duration * 1000, 2)

        except Exception as e:
            logger.warning("Streaming throughput test failed: %s. Falling back to non-streaming.", e)
            start_t = time.perf_counter()
            non_stream_req = ChatCompletionRequest(
                model=model_name,
                messages=[ChatMessage(role="user", content=test_prompt)],
                max_tokens=128,
            )
            res = await provider.chat_completion(non_stream_req)
            total_duration = max(0.001, time.perf_counter() - start_t)
            tokens = res.usage.get("completion_tokens", len((res.content or "").split()))
            tokens_per_sec = round(tokens / total_duration, 2)
            ttft_ms = round(total_duration * 1000, 2)

        # ---------------------------------------------------------
        # Test 2: Structured JSON Generation Compliance
        # ---------------------------------------------------------
        json_score = 0.0
        try:
            json_req = ChatCompletionRequest(
                model=model_name,
                messages=[
                    ChatMessage(
                        role="user",
                        content="Return a JSON object with keys 'name' (string) and 'version' (number). Only JSON.",
                    )
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=64,
            )
            json_resp = await provider.chat_completion(json_req)
            content = (json_resp.content or "").strip()
            # Clean possible markdown fences
            if content.startswith("```"):
                lines = content.splitlines()
                content = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            parsed = json.loads(content)
            if "name" in parsed and "version" in parsed:
                json_score = 1.0
            else:
                json_score = 0.5  # Valid JSON but missing keys
        except Exception:
            json_score = 0.0

        # ---------------------------------------------------------
        # Test 3: Multi-Constraint Instruction Following
        # ---------------------------------------------------------
        instruction_score = 0.0
        try:
            inst_prompt = "Reply with exactly three words, separated by commas, all uppercase: RED, GREEN, BLUE."
            inst_req = ChatCompletionRequest(
                model=model_name,
                messages=[ChatMessage(role="user", content=inst_prompt)],
                temperature=0.0,
                max_tokens=32,
            )
            inst_resp = await provider.chat_completion(inst_req)
            text = (inst_resp.content or "").strip().upper()
            items = [item.strip() for item in text.split(",")]
            if len(items) == 3 and all(w in ["RED", "GREEN", "BLUE"] for w in items):
                instruction_score = 1.0
            elif len(items) == 3:
                instruction_score = 0.6
            elif any(w in text for w in ["RED", "GREEN", "BLUE"]):
                instruction_score = 0.3
        except Exception:
            instruction_score = 0.0

        # ---------------------------------------------------------
        # Test 4: Tool-Calling Capability
        # ---------------------------------------------------------
        tool_calling_supported = False
        try:
            caps = await provider.get_capabilities(model_name)
            tool_calling_supported = caps.supports_tools
        except Exception:
            tool_calling_supported = False

        hw_after = self.sample_hardware()

        # Hardware Assessment
        hardware_notes = "Compatible with host hardware."
        if hw_after["vram_used_mb"] and hw_after["vram_total_mb"]:
            if hw_after["vram_used_mb"] > 3500:
                hardware_notes = "WARNING: VRAM usage exceeds 3.5 GB! Pascal CC 6.1 GPU ceiling near saturation."

        metric = BenchmarkMetric(
            model_name=model_name,
            provider_id=provider_name,
            timestamp=datetime.now(timezone.utc).isoformat(),
            ttft_ms=ttft_ms,
            tokens_per_sec=tokens_per_sec,
            ram_used_mb=hw_after["ram_used_mb"],
            vram_used_mb=hw_after["vram_used_mb"],
            gpu_temp_c=hw_after["gpu_temp_c"],
            structured_json_score=json_score,
            instruction_following_score=instruction_score,
            tool_calling_supported=tool_calling_supported,
            hardware_notes=hardware_notes,
            raw_metrics={
                "hardware_before": hw_before,
                "hardware_after": hw_after,
            },
        )

        # ---------------------------------------------------------
        # Persist to Database
        # ---------------------------------------------------------
        if self.db:
            try:
                await self.db.execute_write(
                    """
                    INSERT INTO model_benchmarks (
                        model_name, provider_id, timestamp, ttft_ms, tokens_per_sec,
                        ram_used_mb, vram_used_mb, gpu_temp_c, structured_json_score,
                        instruction_following_score, tool_calling_supported, raw_metrics_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        metric.model_name,
                        metric.provider_id,
                        metric.timestamp,
                        metric.ttft_ms,
                        metric.tokens_per_sec,
                        metric.ram_used_mb,
                        metric.vram_used_mb,
                        metric.gpu_temp_c,
                        metric.structured_json_score,
                        metric.instruction_following_score,
                        1 if metric.tool_calling_supported else 0,
                        json.dumps(metric.raw_metrics),
                    ),
                )
                logger.info("Persisted benchmark metric for '%s' to database.", model_name)
            except Exception as db_err:
                logger.error("Failed to persist benchmark results: %s", db_err)

        return metric
