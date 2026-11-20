"""Empirical Performance and Hardware Benchmark Script for Milestone 05 Personal Memory."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import aiosqlite
import httpx
import numpy as np
import psutil

from zoro.core.nvml_telemetry import NVMLSampler
from zoro.memory.embeddings import LocalEmbeddingEngine
from zoro.memory.manager import MemoryManager
from zoro.memory.models import MemoryCategory, MemoryCreate, MemoryFilter
from zoro.storage.migrations import MigrationRunner


async def run_benchmark():
    print("=" * 70)
    print("PROJECT ZORO — MILESTONE 05 HARDWARE & MEMORY BENCHMARK")
    print("=" * 70)

    # 1. Hardware baseline
    nvml = NVMLSampler()
    has_nvml = nvml.initialize()
    gpu_metrics = nvml.sample() if has_nvml else {}
    proc = psutil.Process(os.getpid())

    print(f"OS: Windows {sys.getwindowsversion().major} (Build {sys.getwindowsversion().build})")
    print(f"CPU Logical Cores: {psutil.cpu_count(logical=True)}")
    print(f"Total System RAM: {psutil.virtual_memory().total / (1024**3):.2f} GB")
    if has_nvml:
        print(f"GPU: {gpu_metrics.get('gpu_name', 'NVIDIA')}")
        print(f"Initial VRAM Used: {gpu_metrics.get('vram_used_mb', 0):.1f} MB / {gpu_metrics.get('vram_total_mb', 0):.1f} MB")
        print(f"Initial GPU Temp: {gpu_metrics.get('gpu_temperature_c', 0)} °C")

    # 2. Benchmark Embedding Latency (all-minilm)
    embedder = LocalEmbeddingEngine()
    test_phrase = "The owner is developing a distributed Windows AI assistant using Python and SQLite."

    # Cold embedding
    t0 = time.perf_counter()
    v1 = embedder.embed_text(test_phrase)
    cold_embed_ms = (time.perf_counter() - t0) * 1000
    print(f"\n[Embedding Benchmark]")
    print(f"Cold Embedding Latency: {cold_embed_ms:.2f} ms (Dimension: {len(v1)})")

    # Warm embedding (10 iterations)
    warm_latencies = []
    phrases = [
        "User prefers dark mode and JetBrains Mono.",
        "Developing restaurant point-of-sale system.",
        "Final exam scheduled on December 15th.",
        "Completed milestone 04 audio verification.",
        "Decided to migrate to SQLite hybrid search.",
    ]
    for p in phrases:
        t_start = time.perf_counter()
        _ = embedder.embed_text(p)
        warm_latencies.append((time.perf_counter() - t_start) * 1000)

    avg_warm_ms = sum(warm_latencies) / len(warm_latencies)
    print(f"Average Warm Embedding Latency: {avg_warm_ms:.2f} ms")

    # 3. Benchmark Database and Hybrid Retrieval
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        async with aiosqlite.connect(db_path) as conn:
            await MigrationRunner.run_migrations(conn)

        mem_mgr = MemoryManager(db_path=db_path, embedding_engine=embedder)

        # Populate with 100 test memories
        print("\n[Populating Memory Store with 100 Records...]")
        t_pop_start = time.perf_counter()
        for i in range(100):
            cat = [MemoryCategory.IDENTITY, MemoryCategory.PREFERENCE, MemoryCategory.PROJECT, MemoryCategory.SCHEDULE, MemoryCategory.EPISODIC][i % 5]
            await mem_mgr.store.create_memory(
                MemoryCreate(
                    category=cat,
                    content=f"Synthetic benchmark memory {i}: user has established workflow {i} with specific tool configurations.",
                    importance=0.5 + (i % 5) * 0.1,
                    project_name=f"Project_{i % 10}",
                )
            )
        pop_time_sec = time.perf_counter() - t_pop_start
        print(f"Populated 100 memories in {pop_time_sec:.2f} s ({pop_time_sec / 100 * 1000:.1f} ms/record)")

        # Benchmark Retrieval
        print("\n[Retrieval Latency Benchmark]")
        # A. FTS5 Keyword only
        t_kw = time.perf_counter()
        kw_results = await mem_mgr.store.search("workflow 42", min_score=0.1, semantic_weight=0.0, keyword_weight=1.0)
        kw_ms = (time.perf_counter() - t_kw) * 1000
        print(f"FTS5 Keyword Search Latency: {kw_ms:.2f} ms (Found: {len(kw_results)})")

        # B. Dense Vector Semantic only
        t_sem = time.perf_counter()
        sem_results = await mem_mgr.store.search("tool configurations and workflows", min_score=0.1, semantic_weight=1.0, keyword_weight=0.0)
        sem_ms = (time.perf_counter() - t_sem) * 1000
        print(f"Dense Vector Semantic Search Latency: {sem_ms:.2f} ms (Found: {len(sem_results)})")

        # C. Combined Hybrid (Semantic + Keyword + Context Building)
        t_hyb = time.perf_counter()
        context_block = await mem_mgr.get_context_for_prompt("What workflows and tool configurations do I use?")
        hyb_ms = (time.perf_counter() - t_hyb) * 1000
        print(f"End-to-End Context Retrieval Latency: {hyb_ms:.2f} ms")
        print(f"Context Block Length: {len(context_block)} characters")

        # 4. System & GPU Telemetry under load
        mem_info = proc.memory_info()
        gpu_after = nvml.sample() if has_nvml else {}

        print("\n[Resource Consumption]")
        print(f"Process Resident RAM (RSS): {mem_info.rss / (1024**2):.2f} MB")
        if has_nvml:
            print(f"Active GPU VRAM Used: {gpu_after.get('vram_used_mb', 0):.1f} MB / {gpu_after.get('vram_total_mb', 0):.1f} MB")
            print(f"Free GPU VRAM Headroom: {gpu_after.get('vram_free_mb', 0):.1f} MB")
            print(f"GPU Operating Temperature: {gpu_after.get('gpu_temperature_c', 0)} °C")

        results = {
            "cold_embed_ms": round(cold_embed_ms, 2),
            "avg_warm_embed_ms": round(avg_warm_ms, 2),
            "pop_100_records_sec": round(pop_time_sec, 2),
            "fts5_keyword_ms": round(kw_ms, 2),
            "dense_semantic_ms": round(sem_ms, 2),
            "hybrid_context_retrieval_ms": round(hyb_ms, 2),
            "rss_ram_mb": round(mem_info.rss / (1024**2), 2),
            "gpu_vram_used_mb": gpu_after.get("vram_used_mb", 0),
            "gpu_vram_free_mb": gpu_after.get("vram_free_mb", 0),
            "gpu_temp_c": gpu_after.get("gpu_temperature_c", 0),
        }

        out_path = Path("reports/milestone_05_benchmark_results.json")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nSaved empirical results to {out_path}")

    finally:
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except OSError:
                pass


if __name__ == "__main__":
    asyncio.run(run_benchmark())
