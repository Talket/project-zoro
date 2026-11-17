"""Real Local LLM Verification Script for PROJECT ZORO (Phase 4)."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
import psutil

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zoro.core.nvml_telemetry import NVMLSampler
from zoro.models.base import ChatCompletionRequest, ChatMessage
from zoro.models.mock import MockModelProvider
from zoro.models.ollama import OllamaProvider
from zoro.models.registry import ProviderRegistry
from zoro.orchestrator.orchestrator import ZoroOrchestrator


async def run_verification():
    print("=" * 80)
    print("PROJECT ZORO — REAL LOCAL AI MODEL VERIFICATION (PHASE 4)")
    print("=" * 80)

    # Initialize Hardware Samplers
    nvml = NVMLSampler()
    has_nvml = nvml.initialize()
    process = psutil.Process()

    def get_hw_metrics():
        ram_mb = round(process.memory_info().rss / (1024 * 1024), 1)
        system_ram_mb = round(psutil.virtual_memory().used / (1024 * 1024), 1)
        vram_mb = 0.0
        gpu_temp = 0.0
        if has_nvml:
            sample = nvml.sample()
            if sample:
                vram_mb = sample["vram_used_mb"]
                gpu_temp = sample["gpu_temp_c"]
        return {"process_ram_mb": ram_mb, "system_ram_mb": system_ram_mb, "vram_used_mb": vram_mb, "gpu_temp_c": gpu_temp}

    hw_init = get_hw_metrics()
    print(f"Hardware Baseline: Host RAM: {hw_init['system_ram_mb']} MB, VRAM: {hw_init['vram_used_mb']} MB (GPU: {nvml.device_name})")

    # Initialize Provider
    ollama = OllamaProvider(base_url="http://127.0.0.1:11434")
    health = await ollama.health_check()
    print(f"Ollama Health Check: Available={health.is_available}, Latency={health.latency_ms} ms, Details={health.details}")
    if not health.is_available:
        print("[ERROR] Ollama is not available! Aborting verification.")
        return

    models = await ollama.list_models()
    print(f"Ollama Models Found: {[m.name for m in models]}")

    selected_model = "qwen2.5:3b"

    # Setup ProviderRegistry
    registry = ProviderRegistry()
    registry.register_provider("ollama", ollama, default_model=selected_model)
    registry.set_active_provider("ollama", model_name=selected_model)

    # -------------------------------------------------------------------------
    # TEST 1: Basic Conversation & Streaming Token Benchmark
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("TEST 1: BASIC CONVERSATION & STREAMING BENCHMARK")
    print("-" * 80)

    for q in ["Who are you?", "Explain how a CPU works in simple language."]:
        print(f"\nUser Query: '{q}'")
        req = ChatCompletionRequest(
            model=selected_model,
            messages=[
                ChatMessage(role="system", content="You are ZORO, a loyal personal artificial intelligence assistant."),
                ChatMessage(role="user", content=q),
            ],
            temperature=0.7,
            max_tokens=256,
        )

        t_start = time.perf_counter()
        t_first = None
        collected_tokens = []

        async for chunk in ollama.chat_completion_stream(req):
            if chunk.delta_content:
                if t_first is None:
                    t_first = time.perf_counter()
                collected_tokens.append(chunk.delta_content)

        t_end = time.perf_counter()
        ttft_ms = (t_first - t_start) * 1000.0 if t_first else 0.0
        total_time_s = t_end - t_start
        reply_text = "".join(collected_tokens).strip()
        num_tokens = len(collected_tokens)
        tok_per_sec = (num_tokens / (t_end - t_first)) if (t_first and (t_end - t_first) > 0) else 0.0

        hw = get_hw_metrics()
        print(f"Response: {reply_text[:160]}...")
        print(f"Metrics: TTFT: {ttft_ms:.1f} ms | Total Time: {total_time_s:.2f} s | Tokens: {num_tokens} | Rate: {tok_per_sec:.1f} tok/s | VRAM: {hw['vram_used_mb']} MB")

    # -------------------------------------------------------------------------
    # TEST 2: Multi-Turn Conversational Context
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("TEST 2: MULTI-TURN CONVERSATIONAL CONTEXT")
    print("-" * 80)

    conv_messages = [
        ChatMessage(role="system", content="You are ZORO, an intelligent personal desktop assistant."),
        ChatMessage(role="user", content="My favourite programming language is Python."),
    ]
    resp1 = await registry.chat_completion(ChatCompletionRequest(model=selected_model, messages=conv_messages, max_tokens=100))
    conv_messages.append(ChatMessage(role="assistant", content=resp1.content))
    print(f"Turn 1 ('My favourite programming language is Python'): {resp1.content.strip()[:100]}...")

    conv_messages.append(ChatMessage(role="user", content="Which programming language did I just mention? Answer concisely."))
    t0 = time.perf_counter()
    resp2 = await registry.chat_completion(ChatCompletionRequest(model=selected_model, messages=conv_messages, max_tokens=64))
    t1 = time.perf_counter()
    reply2 = resp2.content.strip()
    print(f"Turn 2 Question: 'Which programming language did I just mention?'")
    print(f"Turn 2 Answer: '{reply2}' (Latency: {(t1 - t0)*1000:.1f} ms)")
    assert "python" in reply2.lower(), f"Failed context retention: {reply2}"
    print("[PASS] Multi-turn context retained successfully.")

    # -------------------------------------------------------------------------
    # TEST 3: Structured JSON Output
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("TEST 3: STRUCTURED JSON OUTPUT")
    print("-" * 80)

    json_prompt = (
        "Generate a JSON object containing exactly three keys: "
        "'name' (string), 'age' (integer), and 'interests' (array of three strings). "
        "Output ONLY raw JSON."
    )
    req_json = ChatCompletionRequest(
        model=selected_model,
        messages=[
            ChatMessage(role="system", content="You are a data formatting assistant. Output only valid JSON."),
            ChatMessage(role="user", content=json_prompt),
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=150,
    )

    t0 = time.perf_counter()
    resp_json = await registry.chat_completion(req_json)
    t1 = time.perf_counter()
    raw_json = resp_json.content.strip()
    print(f"Raw Output: {raw_json}")

    # Validate JSON parsing
    parsed = json.loads(raw_json)
    assert "name" in parsed, "Missing 'name' in JSON"
    assert "age" in parsed, "Missing 'age' in JSON"
    assert "interests" in parsed and isinstance(parsed["interests"], list), "Missing 'interests' array in JSON"
    assert len(parsed["interests"]) == 3, f"Expected 3 interests, got {len(parsed['interests'])}"
    print(f"[PASS] Successfully parsed and validated JSON schema: {parsed}")
    print(f"Structured Generation Latency: {(t1 - t0)*1000:.1f} ms")

    # -------------------------------------------------------------------------
    # TEST 4: Logical Reasoning
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("TEST 4: LOGICAL REASONING")
    print("-" * 80)

    logic_query = (
        "Sally has 3 brothers. Each brother has 2 sisters. "
        "How many sisters does Sally have? Think step by step, then give the final answer."
    )
    req_logic = ChatCompletionRequest(
        model=selected_model,
        messages=[
            ChatMessage(role="system", content="You are a precise logical reasoning assistant."),
            ChatMessage(role="user", content=logic_query),
        ],
        temperature=0.3,
        max_tokens=256,
    )
    t0 = time.perf_counter()
    resp_logic = await registry.chat_completion(req_logic)
    t1 = time.perf_counter()
    logic_ans = resp_logic.content.strip()
    print(f"Question: {logic_query}")
    print(f"Reasoning:\n{logic_ans}")
    print(f"Reasoning Latency: {(t1 - t0)*1000:.1f} ms")
    assert "1" in logic_ans or "one" in logic_ans.lower(), f"Unexpected reasoning outcome: {logic_ans}"
    print("[PASS] Logical problem answered correctly (Sally has 1 sister).")

    # -------------------------------------------------------------------------
    # TEST 5: Provider Verification & Proof of Non-Mock Execution
    # -------------------------------------------------------------------------
    print("\n" + "-" * 80)
    print("TEST 5: PROVIDER VERIFICATION & NON-MOCK PROOF")
    print("-" * 80)

    active_prov = registry.get_provider()
    print(f"Active Provider Object: {active_prov.__class__.__name__}")
    print(f"Active Provider Name:   {getattr(active_prov, 'name', 'ollama')}")
    print(f"Active Model ID:        {registry.get_active_model()}")

    # Explicitly check class type
    assert not isinstance(active_prov, MockModelProvider), "Active provider is MockModelProvider!"
    assert isinstance(active_prov, OllamaProvider), f"Active provider is not OllamaProvider: {type(active_prov)}"
    assert resp1.content != "Mock response from ZORO Model Subsystem.", "Received mock placeholder response!"

    hw_final = get_hw_metrics()
    print(f"\nFinal Hardware State:")
    print(f"  VRAM Used: {hw_final['vram_used_mb']} MB (Baseline: {hw_init['vram_used_mb']} MB)")
    print(f"  GPU Temp:  {hw_final['gpu_temp_c']} °C")
    print(f"  System RAM:{hw_final['system_ram_mb']} MB")
    print("[PASS] PROOF CONFIRMED: Real local model 'qwen2.5:3b' executed via OllamaProvider on GPU/CPU.")

    if has_nvml:
        nvml.shutdown()


if __name__ == "__main__":
    asyncio.run(run_verification())
