"""PROJECT ZORO — Verification Test 06: Actual User Readiness & Subsystem Audit."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zoro.core.engine import ZoroEngine
from zoro.ipc.pipe_client import NamedPipeClient


async def run_test_06() -> dict:
    results = {}
    print("=" * 70)
    print("VERIFICATION TEST 06: ACTUAL USER READINESS & SUBSYSTEM AUDIT")
    print("=" * 70)

    # 1. Initialize ZoroEngine
    print("\n[6.1] Initializing ZoroEngine with real local hardware & Ollama...")
    engine = ZoroEngine()
    t0 = time.perf_counter()
    init_ok = await engine.initialize()
    init_time_ms = (time.perf_counter() - t0) * 1000.0

    print(f"  Engine Initialization: Success={init_ok}, Latency={init_time_ms:.1f}ms")
    assert init_ok is True, "ZoroEngine failed to initialize!"

    results["6.1_engine_init"] = {
        "status": "PASS",
        "init_success": init_ok,
        "latency_ms": round(init_time_ms, 2),
    }

    # 2. Connect via Named Pipe IPC
    print("\n[6.2] Connecting IPC Client via Named Pipe '\\\\.\\pipe\\zoro-ipc-main'...")
    client = NamedPipeClient(pipe_name=r"\\.\pipe\zoro-ipc-main")
    connected = client.connect(timeout_ms=5000)
    print(f"  IPC Client Connected: {connected}")
    assert connected is True, "Failed to connect to ZoroEngine Named Pipe server!"

    # Test system.echo
    echo_res = client.send_request("system.echo", {"message": "Auditor ping"})
    print(f"  system.echo: {echo_res}")
    assert echo_res.get("echo") == "Auditor ping"

    # Test system.get_health
    health_res = client.send_request("system.get_health", {})
    print(f"  system.get_health: cpu={health_res.get('cpu_percent')}%, ram={health_res.get('ram_used_mb')}MB, gpu={health_res.get('gpu_name')}")
    assert "cpu_percent" in health_res and "ram_used_mb" in health_res

    # Test ai.get_providers
    ai_res = client.send_request("ai.get_providers", {})
    print(f"  ai.get_providers: active='{ai_res.get('active_provider')}', model='{ai_res.get('active_model')}'")
    assert ai_res.get("active_provider") == "ollama", f"Expected active provider 'ollama', got {ai_res.get('active_provider')}"

    # Test voice.get_status
    voice_res = client.send_request("voice.get_status", {})
    print(f"  voice.get_status: state='{voice_res.get('state')}', stt='{voice_res.get('stt_provider')}', tts='{voice_res.get('tts_provider')}'")
    assert voice_res.get("stt_provider") == "faster-whisper"
    assert voice_res.get("tts_provider") == "windows-sapi"

    # Test voice.get_devices
    dev_res = client.send_request("voice.get_devices", {})
    in_count = len(dev_res.get("input_devices", []))
    out_count = len(dev_res.get("output_devices", []))
    print(f"  voice.get_devices: Discovered {in_count} input, {out_count} output devices via IPC")
    assert in_count > 0 and out_count > 0

    results["6.2_ipc_subsystems"] = {
        "status": "PASS",
        "ipc_connected": connected,
        "active_ai_provider": ai_res.get("active_provider"),
        "active_ai_model": ai_res.get("active_model"),
        "active_stt": voice_res.get("stt_provider"),
        "active_tts": voice_res.get("tts_provider"),
        "input_devices_count": in_count,
        "output_devices_count": out_count,
    }

    # 3. Disconnect and Shutdown Engine
    print("\n[6.3] Testing clean shutdown of engine and background threads...")
    client.close()
    t_shut_0 = time.perf_counter()
    await engine.shutdown()
    shut_ms = (time.perf_counter() - t_shut_0) * 1000.0
    print(f"  Engine Shutdown: Latency={shut_ms:.1f}ms")

    results["6.3_clean_shutdown"] = {
        "status": "PASS",
        "shutdown_latency_ms": round(shut_ms, 2),
    }

    print("\n>>> ALL SUBTESTS IN VERIFICATION TEST 06 PASSED <<<")
    return results


if __name__ == "__main__":
    res = asyncio.run(run_test_06())
    print("\nFinal Results JSON:")
    print(json.dumps(res, indent=2))
