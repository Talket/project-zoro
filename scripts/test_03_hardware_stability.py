"""PROJECT ZORO — Verification Test 03: Hardware & Resource Stability."""

import asyncio
import io
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import psutil
from zoro.core.event_bus import AsyncEventBus
from zoro.core.nvml_telemetry import NVMLSampler
from zoro.models.base import ChatCompletionRequest, ChatMessage
from zoro.models.ollama import OllamaProvider
from zoro.models.registry import ProviderRegistry
from zoro.orchestrator.orchestrator import ZoroOrchestrator
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.tools.registry import ToolRegistry
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.stt.faster_whisper import FasterWhisperProvider
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.tts.sapi import WindowsSapiTTSProvider


def get_process_metrics():
    current_proc = psutil.Process(os.getpid())
    zoro_rss = current_proc.memory_info().rss / (1024**2)
    cpu_percent = psutil.cpu_percent(interval=0.1)

    # Find Ollama processes
    ollama_rss = 0.0
    for p in psutil.process_iter(['name', 'memory_info']):
        try:
            if "ollama" in p.info['name'].lower():
                ollama_rss += p.info['memory_info'].rss / (1024**2)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    sys_mem = psutil.virtual_memory()
    total_ram_gb = sys_mem.total / (1024**3)
    used_ram_gb = sys_mem.used / (1024**3)
    free_ram_gb = sys_mem.available / (1024**3)

    return {
        "zoro_ram_mb": round(zoro_rss, 2),
        "ollama_ram_mb": round(ollama_rss, 2),
        "system_ram_total_gb": round(total_ram_gb, 2),
        "system_ram_used_gb": round(used_ram_gb, 2),
        "system_ram_free_gb": round(free_ram_gb, 2),
        "system_cpu_percent": round(cpu_percent, 1),
    }


async def run_test_03() -> dict:
    results = {}
    print("=" * 70)
    print("VERIFICATION TEST 03: HARDWARE & RESOURCE STABILITY")
    print("=" * 70)

    nvml = NVMLSampler()
    nvml_ok = nvml.initialize()
    print(f"NVML Initialized: {nvml_ok} (Device: {nvml.device_name if nvml_ok else 'N/A'})")

    def sample_hw():
        metrics = get_process_metrics()
        if nvml_ok:
            gpu_sample = nvml.sample()
            metrics.update({
                "gpu_name": nvml.device_name,
                "gpu_vram_total_mb": gpu_sample["vram_total_mb"],
                "gpu_vram_used_mb": gpu_sample["vram_used_mb"],
                "gpu_vram_free_mb": gpu_sample["vram_free_mb"],
                "gpu_temp_c": gpu_sample["gpu_temp_c"],
                "gpu_utilization_percent": gpu_sample["gpu_utilization_percent"],
            })
        else:
            metrics.update({
                "gpu_name": "N/A",
                "gpu_temp_c": "INACCESSIBLE",
            })
        metrics["cpu_temp_c"] = "INACCESSIBLE (Requires privileged kernel driver on Win11)"
        return metrics

    # -------------------------------------------------------------
    # Condition A: ZORO Idle
    # -------------------------------------------------------------
    print("\n[Condition A] Measuring baseline when ZORO is IDLE...")
    time.sleep(1.0)
    cond_a = sample_hw()
    print(f"  ZORO RAM: {cond_a['zoro_ram_mb']} MB | Ollama RAM: {cond_a['ollama_ram_mb']} MB | CPU: {cond_a['system_cpu_percent']}%")
    if nvml_ok:
        print(f"  GPU VRAM Used: {cond_a['gpu_vram_used_mb']} MB / {cond_a['gpu_vram_total_mb']} MB | Temp: {cond_a['gpu_temp_c']} C")
    results["condition_a_idle"] = cond_a

    # -------------------------------------------------------------
    # Condition B: Ollama Model Loaded but Idle
    # -------------------------------------------------------------
    print("\n[Condition B] Loading Qwen2.5 3B into memory and measuring IDLE state...")
    ollama_prov = OllamaProvider(base_url="http://127.0.0.1:11434")
    # Warmup / Load pass
    t_load_0 = time.perf_counter()
    load_req = ChatCompletionRequest(
        model="qwen2.5:3b",
        messages=[ChatMessage(role="user", content="Ping")],
        max_tokens=2,
    )
    load_resp = await ollama_prov.chat_completion(load_req)
    load_time_ms = (time.perf_counter() - t_load_0) * 1000.0
    print(f"  Model Warmup Latency: {load_time_ms:.1f} ms")

    time.sleep(1.0)
    cond_b = sample_hw()
    cond_b["model_load_time_ms"] = round(load_time_ms, 2)
    print(f"  ZORO RAM: {cond_b['zoro_ram_mb']} MB | Ollama RAM: {cond_b['ollama_ram_mb']} MB | CPU: {cond_b['system_cpu_percent']}%")
    if nvml_ok:
        print(f"  GPU VRAM Used: {cond_b['gpu_vram_used_mb']} MB / {cond_b['gpu_vram_total_mb']} MB | Temp: {cond_b['gpu_temp_c']} C")
    results["condition_b_model_loaded_idle"] = cond_b

    # -------------------------------------------------------------
    # Condition C: During Normal AI Conversation
    # -------------------------------------------------------------
    print("\n[Condition C] Measuring hardware usage during active AI Conversation...")
    conv_req = ChatCompletionRequest(
        model="qwen2.5:3b",
        messages=[
            ChatMessage(role="system", content="You are ZORO."),
            ChatMessage(role="user", content="Explain quantum entanglement in 3 sentences."),
        ],
        temperature=0.7,
        max_tokens=150,
    )
    t_c_0 = time.perf_counter()
    conv_resp = await ollama_prov.chat_completion(conv_req)
    latency_c_ms = (time.perf_counter() - t_c_0) * 1000.0
    tokens_c = conv_resp.usage.get("completion_tokens", 1)
    tok_sec_c = tokens_c / (latency_c_ms / 1000.0)

    cond_c = sample_hw()
    cond_c.update({
        "first_response_latency_ms": round(latency_c_ms, 2),
        "completion_tokens": tokens_c,
        "throughput_tok_sec": round(tok_sec_c, 1),
    })
    print(f"  Conversation TTFT/Latency: {latency_c_ms:.1f} ms | Tokens: {tokens_c} | Speed: {tok_sec_c:.1f} tok/s")
    print(f"  ZORO RAM: {cond_c['zoro_ram_mb']} MB | Ollama RAM: {cond_c['ollama_ram_mb']} MB | Temp: {cond_c['gpu_temp_c']} C")
    results["condition_c_normal_ai_conversation"] = cond_c

    # -------------------------------------------------------------
    # Condition D: During Active Voice Interaction (STT + LLM + TTS)
    # -------------------------------------------------------------
    print("\n[Condition D] Measuring hardware usage during full Voice Interaction (FasterWhisper + Ollama + SAPI5)...")
    from zoro.voice.models import STTConfig
    stt = FasterWhisperProvider(config=STTConfig(model_name="tiny.en", device="cpu", compute_type="int8"))
    await stt.load()
    sapi = WindowsSapiTTSProvider()
    await sapi.load()

    # Synthesize audio, transcribe, query LLM, synthesize TTS
    t_d_0 = time.perf_counter()
    sample_speech = await sapi.synthesize("Tell me what is the speed of sound?")
    stt_out = await stt.transcribe(sample_speech)
    llm_out = await ollama_prov.chat_completion(ChatCompletionRequest(
        model="qwen2.5:3b",
        messages=[ChatMessage(role="user", content=stt_out.transcript)],
        max_tokens=80,
    ))
    tts_out = await sapi.synthesize(llm_out.content[:100])
    latency_d_ms = (time.perf_counter() - t_d_0) * 1000.0

    cond_d = sample_hw()
    cond_d.update({
        "voice_turnaround_total_ms": round(latency_d_ms, 2),
        "stt_transcript": stt_out.transcript,
        "tts_payload_bytes": len(tts_out),
    })
    print(f"  Full Voice Interaction Turnaround: {latency_d_ms:.1f} ms")
    print(f"  ZORO RAM: {cond_d['zoro_ram_mb']} MB | Ollama RAM: {cond_d['ollama_ram_mb']} MB | Temp: {cond_d['gpu_temp_c']} C")
    results["condition_d_voice_interaction"] = cond_d

    # -------------------------------------------------------------
    # Condition E: Continuous Stability Test (Consecutive Interactions)
    # -------------------------------------------------------------
    print("\n[Condition E] Continuous Multi-Turn Stability & Memory Leak Stress Test (5 Iterations)...")
    start_ram = get_process_metrics()["zoro_ram_mb"]
    iteration_stats = []

    for i in range(1, 6):
        t_iter_0 = time.perf_counter()
        query = f"Provide a one-sentence historical fact about the number {i}."
        resp = await ollama_prov.chat_completion(ChatCompletionRequest(
            model="qwen2.5:3b",
            messages=[ChatMessage(role="user", content=query)],
            max_tokens=60,
        ))
        iter_ms = (time.perf_counter() - t_iter_0) * 1000.0
        toks = resp.usage.get("completion_tokens", 1)
        speed = toks / (iter_ms / 1000.0)

        hw_snap = sample_hw()
        iteration_stats.append({
            "iteration": i,
            "latency_ms": round(iter_ms, 2),
            "tokens": toks,
            "speed_tok_sec": round(speed, 1),
            "zoro_ram_mb": hw_snap["zoro_ram_mb"],
            "gpu_vram_used_mb": hw_snap.get("gpu_vram_used_mb"),
            "gpu_temp_c": hw_snap.get("gpu_temp_c"),
        })
        print(f"  [Iter {i}/5] Latency: {iter_ms:.1f}ms | Tokens: {toks} ({speed:.1f} tok/s) | ZORO RAM: {hw_snap['zoro_ram_mb']} MB | VRAM: {hw_snap.get('gpu_vram_used_mb')} MB")

    end_ram = get_process_metrics()["zoro_ram_mb"]
    ram_growth = end_ram - start_ram
    print(f"\n  Memory Profile: Start={start_ram} MB, End={end_ram} MB, Net Growth={ram_growth:.2f} MB")
    assert ram_growth < 150.0, f"Unacceptable memory growth / leak detected: {ram_growth:.2f} MB"

    cond_e = {
        "status": "PASS",
        "iterations_completed": 5,
        "initial_zoro_ram_mb": start_ram,
        "final_zoro_ram_mb": end_ram,
        "net_ram_growth_mb": round(ram_growth, 2),
        "iteration_metrics": iteration_stats,
    }
    results["condition_e_continuous_stability"] = cond_e

    if nvml_ok:
        nvml.shutdown()

    print("\n>>> ALL SUBTESTS IN VERIFICATION TEST 03 PASSED <<<")
    return results


if __name__ == "__main__":
    res = asyncio.run(run_test_03())
    print("\nFinal Results JSON:")
    print(json.dumps(res, indent=2))
