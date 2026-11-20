"""PROJECT ZORO — Verification Test 02: Real Voice Pipeline & Ollama Qwen2.5 3B End-to-End."""

import asyncio
import io
import json
import os
import sys
import time
import wave
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sounddevice as sd
from zoro.models.base import ChatCompletionRequest, ChatMessage
from zoro.models.ollama import OllamaProvider
from zoro.models.registry import ProviderRegistry
from zoro.orchestrator.orchestrator import ZoroOrchestrator
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.tools.registry import ToolRegistry
from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.devices import AudioDeviceManager
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.interruption import InterruptionManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.stt.faster_whisper import FasterWhisperProvider
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.tts.sapi import WindowsSapiTTSProvider


async def run_test_02() -> dict:
    results = {}
    print("=" * 70)
    print("VERIFICATION TEST 02: REAL VOICE PIPELINE & OLLAMA QWEN2.5 3B")
    print("=" * 70)

    # -------------------------------------------------------------
    # 2.1 Hardware Microphone & Audio Devices Detection
    # -------------------------------------------------------------
    print("\n[Subtest 2.1] Detecting physical microphone and output devices...")
    dev_mgr = AudioDeviceManager()
    input_devs = dev_mgr.list_input_devices()
    output_devs = dev_mgr.list_output_devices()
    default_in = dev_mgr.get_default_input_device()
    default_out = dev_mgr.get_default_output_device()

    print(f"  Input Devices Found: {len(input_devs)}")
    for d in input_devs:
        print(f"    - [{d.index}] {d.name} (ch={d.channels}, {d.sample_rate}Hz)")
    print(f"  Output Devices Found: {len(output_devs)}")
    for d in output_devs:
        print(f"    - [{d.index}] {d.name} (ch={d.channels}, {d.sample_rate}Hz)")

    print(f"  Default Input: {default_in.name if default_in else 'None'}")
    print(f"  Default Output: {default_out.name if default_out else 'None'}")

    assert len(input_devs) > 0, "No input audio devices detected on this system!"
    assert len(output_devs) > 0, "No output audio devices detected on this system!"
    assert default_in is not None, "No default microphone detected"

    results["2.1_device_detection"] = {
        "status": "PASS",
        "input_count": len(input_devs),
        "output_count": len(output_devs),
        "default_input": default_in.name,
        "default_output": default_out.name if default_out else None,
    }

    # Verify native microphone capture
    print("  Testing native microphone capture initialization...")
    cap = AudioCaptureManager(sample_rate=16000, channels=1)
    cap_ok = cap.start_capture()
    time.sleep(0.5)
    rms = cap.current_rms
    buffered_secs = cap.audio_buffer.current_duration_seconds
    cap.stop_capture()
    print(f"  Capture started: {cap_ok}, RMS Level: {rms:.4f}, Buffered: {buffered_secs:.2f}s")
    assert cap_ok is True, "Failed to initialize microphone capture"

    results["2.1_mic_capture"] = {
        "status": "PASS",
        "capture_started": cap_ok,
        "rms_level": rms,
        "buffered_seconds": buffered_secs,
    }

    # -------------------------------------------------------------
    # 2.2 Text-to-Speech (SAPI5) Audio Generation
    # -------------------------------------------------------------
    print("\n[Subtest 2.2] Testing Windows SAPI5 TTS Engine...")
    sapi = WindowsSapiTTSProvider()
    tts_loaded = await sapi.load()
    assert tts_loaded is True, "Failed to load Windows SAPI5 TTS engine"

    test_sentence = "System operational. Project Zoro voice engine is active."
    t0 = time.perf_counter()
    audio_bytes = await sapi.synthesize(test_sentence)
    tts_latency_ms = (time.perf_counter() - t0) * 1000.0

    print(f"  SAPI5 synthesis latency: {tts_latency_ms:.2f} ms")
    print(f"  Synthesized audio payload: {len(audio_bytes)} bytes")
    assert len(audio_bytes) > 1000, "SAPI5 synthesized audio payload was empty or abnormally small"

    # Validate generated PCM audio
    sample_rate = 22050
    bytes_per_sample = 2  # 16-bit Mono
    duration_s = len(audio_bytes) / (sample_rate * bytes_per_sample)
    print(f"  PCM Properties: 1 channel, 16-bit, {sample_rate} Hz, Duration: {duration_s:.2f}s")

    results["2.2_tts_generation"] = {
        "status": "PASS",
        "provider": "WindowsSapiTTSProvider",
        "latency_ms": round(tts_latency_ms, 2),
        "audio_bytes": len(audio_bytes),
        "duration_seconds": round(duration_s, 2),
        "sample_rate": sample_rate,
    }

    # -------------------------------------------------------------
    # 2.3 Speech-to-Text (FasterWhisper CPU INT8)
    # -------------------------------------------------------------
    print("\n[Subtest 2.3] Testing FasterWhisper Speech-to-Text with known test phrases...")
    from zoro.voice.models import STTConfig
    stt_cfg = STTConfig(model_name="tiny.en", device="cpu", compute_type="int8")
    stt = FasterWhisperProvider(config=stt_cfg)
    stt_loaded = await stt.load()
    assert stt_loaded is True, "Failed to load FasterWhisper tiny.en model"

    test_phrases = [
        "What is the current time and date?",
        "Open the settings window on my computer.",
        "My favorite programming language is Python.",
    ]

    stt_results = []
    for phrase in test_phrases:
        # Synthesize raw PCM audio for this phrase
        raw_pcm = await sapi.synthesize(phrase)

        t_stt_0 = time.perf_counter()
        stt_resp = await stt.transcribe(raw_pcm)
        stt_latency_ms = (time.perf_counter() - t_stt_0) * 1000.0
        transcript = stt_resp.transcript.strip()

        print(f"  Reference : '{phrase}'")
        print(f"  Recognized: '{transcript}' (Latency: {stt_latency_ms:.1f} ms)")

        # Verify key semantic tokens exist in recognized text
        ref_words = [w.lower().rstrip(".,!?") for w in phrase.split()]
        rec_words = [w.lower().rstrip(".,!?") for w in transcript.split()]
        overlap = set(ref_words).intersection(rec_words)
        match_ratio = len(overlap) / len(ref_words)
        print(f"  Semantic word match ratio: {match_ratio:.2%}")
        assert match_ratio >= 0.70, f"STT recognition accuracy too low: {match_ratio:.2%}"

        stt_results.append({
            "reference": phrase,
            "transcript": transcript,
            "latency_ms": round(stt_latency_ms, 2),
            "match_ratio": round(match_ratio, 2),
        })

    results["2.3_stt_transcription"] = {
        "status": "PASS",
        "model": "Systran/faster-whisper-tiny.en",
        "compute_type": "int8",
        "phrases_tested": stt_results,
    }

    # -------------------------------------------------------------
    # 2.4 Real Ollama Inference (qwen2.5:3b)
    # -------------------------------------------------------------
    print("\n[Subtest 2.4] Verifying Real Ollama Inference (qwen2.5:3b)...")
    ollama_prov = OllamaProvider(base_url="http://127.0.0.1:11434")
    health = await ollama_prov.health_check()
    print(f"  Ollama Health: is_available={health.is_available}, latency={health.latency_ms}ms")
    assert health.is_available is True, "Ollama daemon is offline at 127.0.0.1:11434!"

    # Multi-turn Context Test:
    # Turn 1: Provide personal preference
    # Turn 2: Query personal preference
    print("  Executing real multi-turn conversation test on local qwen2.5:3b...")
    messages = [
        ChatMessage(role="system", content="You are ZORO, a concise Windows AI assistant."),
        ChatMessage(role="user", content="My favorite operating system is Windows 11."),
    ]
    req1 = ChatCompletionRequest(model="qwen2.5:3b", messages=messages, temperature=0.7, max_tokens=128)
    t_llm_0 = time.perf_counter()
    resp1 = await ollama_prov.chat_completion(req1)
    ttft_1_ms = (time.perf_counter() - t_llm_0) * 1000.0

    print(f"  Turn 1 Response: '{resp1.content.strip()}' (Latency: {ttft_1_ms:.1f}ms)")
    assert "mock" not in resp1.content.lower(), "Mock response detected instead of real Ollama!"
    assert resp1.usage["completion_tokens"] > 0, "Zero tokens generated!"

    # Turn 2: Context recall query
    messages.append(ChatMessage(role="assistant", content=resp1.content))
    messages.append(ChatMessage(role="user", content="Which operating system did I just tell you is my favorite? Answer with just the OS name."))

    req2 = ChatCompletionRequest(model="qwen2.5:3b", messages=messages, temperature=0.1, max_tokens=64)
    t_llm_1 = time.perf_counter()
    resp2 = await ollama_prov.chat_completion(req2)
    ttft_2_ms = (time.perf_counter() - t_llm_1) * 1000.0
    completion_toks = resp2.usage.get("completion_tokens", 1)
    tok_per_sec = completion_toks / (ttft_2_ms / 1000.0)

    print(f"  Turn 2 Response: '{resp2.content.strip()}'")
    print(f"  Turn 2 Metrics : Tokens={completion_toks}, TTFT={ttft_2_ms:.1f}ms, Speed={tok_per_sec:.1f} tok/s")

    assert "windows" in resp2.content.lower(), f"Model failed multi-turn context recall! Reply: {resp2.content}"

    results["2.4_real_ollama"] = {
        "status": "PASS",
        "model": "qwen2.5:3b",
        "turn_1_latency_ms": round(ttft_1_ms, 2),
        "turn_2_latency_ms": round(ttft_2_ms, 2),
        "turn_2_tokens": completion_toks,
        "throughput_tok_sec": round(tok_per_sec, 1),
        "context_recall_verified": True,
    }

    # -------------------------------------------------------------
    # 2.5 Integrated Voice Turn Execution (STT -> Orchestrator -> LLM -> TTS)
    # -------------------------------------------------------------
    print("\n[Subtest 2.5] Testing integrated voice turn taking...")
    db_path = PROJECT_ROOT / "reports" / "verification_voice.db"
    if db_path.exists():
        db_path.unlink()
    db = DatabaseManager(db_path=db_path)
    await db.initialize()

    sec_dir = PROJECT_ROOT / "reports" / "verification_voice_sec"
    sec_dir.mkdir(parents=True, exist_ok=True)
    gate = PermissionGate()
    audit = AuditLogger(db=db, checkpoint_path=sec_dir / "audit.checkpoint", key=b"0" * 32)
    emergency_mgr = EmergencyManager(halt_lock_path=sec_dir / "halt.lock", pid_path=sec_dir / "zoro.pid")
    tool_reg = ToolRegistry(db=db, audit=audit, permission_gate=gate)

    prov_reg = ProviderRegistry()
    prov_reg.register_provider("ollama", ollama_prov, default_model="qwen2.5:3b")
    prov_reg.set_active_provider("ollama")

    from zoro.core.event_bus import AsyncEventBus
    orch = ZoroOrchestrator(
        provider_registry=prov_reg,
        tool_registry=tool_reg,
        db=db,
        audit=audit,
        event_bus=AsyncEventBus(),
        emergency_mgr=emergency_mgr,
    )

    tts_reg = TTSRegistry(default_provider="windows-sapi")
    playback = AudioPlaybackManager()
    session_mgr = VoiceSessionManager(db=db)
    await session_mgr.start_session()

    turn_mgr = VoiceTurnManager(
        orchestrator=orch,
        tts_registry=tts_reg,
        playback_manager=playback,
        session_manager=session_mgr,
    )

    spoken_chunks = []
    generated_text = []

    voice_prompt = "What is the speed of light in vacuum?"
    print(f"  Submitting voice prompt to TurnManager: '{voice_prompt}'")
    t_turn_0 = time.perf_counter()
    reply = await turn_mgr.execute_turn(
        user_transcript=voice_prompt,
        on_text_generated=lambda t: generated_text.append(t),
        on_audio_chunk=lambda c: spoken_chunks.append(c),
    )
    turn_latency_ms = (time.perf_counter() - t_turn_0) * 1000.0

    print(f"  Spoken Reply: '{reply[:100]}...'")
    print(f"  Audio Chunks Generated: {len(spoken_chunks)} chunks, Total Size: {sum(len(c) for c in spoken_chunks)} bytes")
    print(f"  Total Voice Turn Latency: {turn_latency_ms:.1f} ms")

    assert len(reply) > 10, "Empty or short voice turn response"
    assert any(num in reply for num in ("299", "300", "186", "constant", "meter", "second")), (
        f"Unexpected or unscientific answer: {reply}"
    )
    assert len(spoken_chunks) > 0, "No audio chunks produced for TTS playback!"

    await session_mgr.end_session()
    await db.close()

    results["2.5_integrated_turn"] = {
        "status": "PASS",
        "prompt": voice_prompt,
        "reply_preview": reply[:120],
        "turn_latency_ms": round(turn_latency_ms, 2),
        "tts_audio_chunks": len(spoken_chunks),
        "tts_total_audio_bytes": sum(len(c) for c in spoken_chunks),
    }

    # -------------------------------------------------------------
    # 2.6 Barge-In Interruption Verification
    # -------------------------------------------------------------
    print("\n[Subtest 2.6] Testing barge-in speech interruption during active playback...")
    interruption_mgr = InterruptionManager(playback_manager=playback)
    interrupted_reasons = []
    interruption_mgr.register_callback(lambda r: interrupted_reasons.append(r))

    playback._is_playing = True
    interruption_mgr._playback_start_time = time.time() - 1.0  # past 0.6s immunity window
    interruption_mgr._last_interruption_time = 0.0

    # Test keyword interruption
    kw_interrupted = interruption_mgr.check_text_interruption("Zoro stop speaking immediately")
    print(f"  Keyword Interruption: Result={kw_interrupted}, Event={interrupted_reasons[-1] if interrupted_reasons else None}")
    assert kw_interrupted is True, "Failed to interrupt on spoken stop keyword!"

    # Test audio frame interruption
    playback._is_playing = True
    interruption_mgr._playback_start_time = time.time() - 1.0
    interruption_mgr._last_interruption_time = 0.0
    import numpy as np
    loud_frame = (np.ones(320, dtype=np.int16) * 16000).tobytes()
    frame_interrupted = interruption_mgr.check_audio_frame(loud_frame)
    print(f"  Loud Audio Frame Interruption: Result={frame_interrupted}, Event={interrupted_reasons[-1] if interrupted_reasons else None}")
    assert frame_interrupted is True, "Failed to interrupt on high-energy acoustic audio frame!"

    playback._is_playing = False

    results["2.6_barge_in"] = {
        "status": "PASS",
        "keyword_interruption": kw_interrupted,
        "acoustic_frame_interruption": frame_interrupted,
        "interruption_events": interrupted_reasons,
    }

    print("\n>>> ALL SUBTESTS IN VERIFICATION TEST 02 PASSED <<<")
    return results


if __name__ == "__main__":
    res = asyncio.run(run_test_02())
    print("\nFinal Results JSON:")
    print(json.dumps(res, indent=2))
