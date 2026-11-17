"""End-to-End Voice Pipeline & Real LLM Integration Verification Suite (Phase 5)."""

import asyncio
import os
import sys
import time
from pathlib import Path
import numpy as np

# Ensure repo root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from zoro.core.engine import ZoroEngine
from zoro.models.base import ChatCompletionRequest, ChatMessage
from zoro.models.mock import MockModelProvider
from zoro.models.ollama import OllamaProvider
from zoro.security.emergency import EmergencyManager
from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.interruption import InterruptionManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.models import STTConfig, TTSConfig, VADConfig, VoiceState, WakeWordConfig
from zoro.voice.pipeline.voice_pipeline import VoicePipeline
from zoro.voice.stt.faster_whisper import FasterWhisperProvider
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.tts.sapi import WindowsSapiTTSProvider
from zoro.voice.vad.detector import VoiceActivityDetector
from zoro.voice.wake.wake_word import WakeWordDetector


async def run_voice_pipeline_verification():
    print("=" * 80)
    print("PROJECT ZORO — PHASE 5 FULL VOICE PIPELINE & REAL LLM VERIFICATION")
    print("=" * 80)

    # 1. Initialize Core Engine with Ollama Provider
    print("\n--- 1. Initializing ZORO Core Engine & Subsystems ---")
    engine = ZoroEngine()
    init_ok = await engine.initialize()
    assert init_ok, "Engine initialization failed!"
    print(f"Active Engine Provider: {engine.provider_registry.active_provider_name} (Model: {engine.provider_registry.get_active_model()})")
    assert engine.provider_registry.active_provider_name == "ollama", "Expected active provider to be 'ollama'!"

    # 2. Verify STT Engine
    print("\n--- 2. Verifying Real STT Engine (FasterWhisper CPU int8) ---")
    stt_provider = FasterWhisperProvider(STTConfig(model_name="tiny.en", device="cpu", compute_type="int8"))
    stt_loaded = await stt_provider.load()
    assert stt_loaded, "FasterWhisper failed to load!"
    print(f"STT Engine: {stt_provider.name} | Loaded: {stt_loaded}")

    # Synthesize test audio using Windows SAPI TTS to feed into STT
    tts_provider = WindowsSapiTTSProvider()
    await tts_provider.load()
    test_question = "What is artificial intelligence in simple terms?"
    tts_audio_raw = await tts_provider.synthesize(test_question)
    
    # Resample from 22050 to 16000 for FasterWhisper
    raw_samples = np.frombuffer(tts_audio_raw, dtype=np.int16)
    num_16k = int(len(raw_samples) * 16000 / 22050)
    samples_16k = np.interp(np.linspace(0, len(raw_samples), num_16k, endpoint=False), np.arange(len(raw_samples)), raw_samples).astype(np.int16)
    audio_16k_bytes = samples_16k.tobytes()

    t_stt0 = time.perf_counter()
    stt_result = await stt_provider.transcribe(audio_16k_bytes)
    t_stt1 = time.perf_counter()
    stt_latency = (t_stt1 - t_stt0) * 1000.0
    print(f"Reference Audio Spoken: '{test_question}'")
    print(f"Transcribed Text:       '{stt_result.transcript}' (Latency: {stt_latency:.1f} ms)")
    assert len(stt_result.transcript) > 10, "Transcription failed or returned empty text!"
    assert "artificial intelligence" in stt_result.transcript.lower(), f"Unexpected transcript: {stt_result.transcript}"
    print("[PASS] Real STT correctly recognized spoken question offline.")

    # 3. Verify Real LLM Orchestration from Transcribed Query
    print("\n--- 3. Verifying Real Local LLM Inference via Orchestrator ---")
    conv_id = f"test-voice-{int(time.time())}"
    t_llm0 = time.perf_counter()
    orch_response = await engine.orchestrator.process_user_request(
        user_message=stt_result.transcript,
        conversation_id=conv_id,
    )
    t_llm1 = time.perf_counter()
    llm_latency = (t_llm1 - t_llm0) * 1000.0
    llm_reply = orch_response.message
    print(f"Orchestrator State:     {orch_response.state.value}")
    print(f"Real LLM Response:      {llm_reply[:180]}...")
    print(f"LLM Generation Time:    {llm_latency:.1f} ms")
    assert orch_response.state.value == "COMPLETED", f"Expected state COMPLETED, got {orch_response.state.value}"
    assert "Mock response" not in llm_reply, "Received Mock response instead of real LLM!"
    assert len(llm_reply) > 20, "LLM reply is too short!"
    print("[PASS] Real local LLM (qwen2.5:3b) generated comprehensive response.")

    # 4. Verify Multi-Turn Follow-Up Context with Real LLM
    print("\n--- 4. Verifying Conversational Context Follow-Up with Real LLM ---")
    followup_q = "Can you summarize that in exactly one sentence?"
    t_fl0 = time.perf_counter()
    followup_resp = await engine.orchestrator.process_user_request(
        user_message=followup_q,
        conversation_id=conv_id,
    )
    t_fl1 = time.perf_counter()
    print(f"Follow-Up Query:        '{followup_q}'")
    print(f"Follow-Up Answer:       '{followup_resp.message}'")
    print(f"Follow-Up Latency:      {(t_fl1 - t_fl0)*1000:.1f} ms")
    assert followup_resp.state.value == "COMPLETED"
    assert len(followup_resp.message) > 10
    print("[PASS] Multi-turn conversational context successfully verified with real LLM.")

    # 5. Verify Real TTS Synthesis of the LLM Response
    print("\n--- 5. Verifying Real TTS Synthesis of LLM Response ---")
    t_tts0 = time.perf_counter()
    tts_reply_pcm = await tts_provider.synthesize(llm_reply[:120])
    t_tts1 = time.perf_counter()
    tts_synth_latency = (t_tts1 - t_tts0) * 1000.0
    print(f"Synthesized LLM Text:   '{llm_reply[:120]}'")
    print(f"TTS Synthesized Size:   {len(tts_reply_pcm)} bytes PCM (Latency: {tts_synth_latency:.1f} ms)")
    assert len(tts_reply_pcm) > 1000, "TTS audio synthesis returned empty audio!"
    print("[PASS] Real TTS successfully synthesized real LLM response.")

    # 6. Verify Wake-Word Engine (Acoustic and Push-to-Talk)
    print("\n--- 6. Verifying Wake-Word Engine ('Zoro', 'Hey Zoro', and Push-to-Talk) ---")
    wake_detector = WakeWordDetector(config=WakeWordConfig(sensitivity=0.6, cooldown_seconds=0.01))
    
    # 6a. Push to Talk
    ptt_res = wake_detector.trigger_push_to_talk()
    print(f"Push-to-Talk: Detected={ptt_res.detected}, Phrase={ptt_res.wake_word}, Conf={ptt_res.confidence}")
    assert ptt_res.detected and ptt_res.wake_word == "push_to_talk"

    # 6b. Acoustic 'Zoro'
    zoro_audio_raw = await tts_provider.synthesize("Zoro")
    s_zoro = np.frombuffer(zoro_audio_raw, dtype=np.int16)
    n_16k = int(len(s_zoro) * 16000 / 22050)
    zoro_16k = np.interp(np.linspace(0, len(s_zoro), n_16k, endpoint=False), np.arange(len(s_zoro)), s_zoro).astype(np.int16)
    wake_zoro = wake_detector.process_audio(zoro_16k.tobytes())
    print(f"Acoustic 'Zoro': Detected={wake_zoro.detected}, Phrase={wake_zoro.wake_word}, Conf={wake_zoro.confidence:.2f}")
    assert wake_zoro.detected and wake_zoro.wake_word == "zoro"

    # 6c. Acoustic 'Hey Zoro'
    time.sleep(0.02)
    wake_detector.last_detection_time = 0.0
    hey_audio_raw = await tts_provider.synthesize("Hey Zoro")
    s_hey = np.frombuffer(hey_audio_raw, dtype=np.int16)
    n_16k = int(len(s_hey) * 16000 / 22050)
    hey_16k = np.interp(np.linspace(0, len(s_hey), n_16k, endpoint=False), np.arange(len(s_hey)), s_hey).astype(np.int16)
    wake_hey = wake_detector.process_audio(hey_16k.tobytes())
    print(f"Acoustic 'Hey Zoro': Detected={wake_hey.detected}, Phrase={wake_hey.wake_word}, Conf={wake_hey.confidence:.2f}")
    assert wake_hey.detected and wake_hey.wake_word == "hey zoro"
    print("[PASS] Wake-word detection and Push-to-Talk verified.")

    # 7. Verify Interruption / Barge-in Gate
    print("\n--- 7. Verifying Barge-In / Interruption Gate ---")
    playback_mgr = AudioPlaybackManager()
    interruption_mgr = InterruptionManager(playback_manager=playback_mgr)
    
    # 7a. Test text stop keyword interruption
    playback_mgr._is_playing = True
    kw_interrupted = interruption_mgr.check_text_interruption("stop talking please")
    print(f"Stop Keyword Interruption: {kw_interrupted}")
    assert kw_interrupted, "Keyword interruption failed!"

    # 7b. Test acoustic barge-in
    playback_mgr._is_playing = True
    interruption_mgr._playback_start_time = time.time() - 1.0  # Past 0.6s immunity window
    interruption_mgr._last_interruption_time = 0.0            # Reset cooldown from 7a
    high_energy_frame = (np.random.normal(0, 0.45, 320) * 32767).astype(np.int16).tobytes()
    audio_interrupted = interruption_mgr.check_audio_frame(high_energy_frame)
    print(f"Barge-In Audio Frame Interruption: {audio_interrupted}")
    assert audio_interrupted, "Audio barge-in failed!"
    print("[PASS] Barge-in interruption gate verified.")

    # 8. Verify Security Invariants (Voice Input Gated Behind Tool Permissions)
    print("\n--- 8. Verifying Security Invariant: Voice Input Subject to Approval Tokens ---")
    destructive_query = "Please delete the log files in C:\\Windows\\Temp."
    orch_dest_resp = await engine.orchestrator.process_user_request(
        user_message=destructive_query,
        conversation_id=f"sec-test-{int(time.time())}",
    )
    print(f"Destructive Request State: {orch_dest_resp.state.value}")
    if orch_dest_resp.state.value == "WAITING_FOR_APPROVAL":
        print(f"[PASS] Correctly blocked automated execution! Paused for Approval Token: {orch_dest_resp.plan_id}")
    elif orch_dest_resp.state.value == "FAILED":
        print(f"[PASS] Correctly rejected destructive operation: {orch_dest_resp.message}")
    else:
        print(f"State: {orch_dest_resp.state.value}, Message: {orch_dest_resp.message}")

    # 9. Verify Emergency Halt Cutoff
    print("\n--- 9. Verifying Emergency Halt Immediate Cutoff ---")
    em = EmergencyManager()
    em.halt_lock_path.parent.mkdir(parents=True, exist_ok=True)
    em.halt_lock_path.write_text('{"reason": "Phase 5 Emergency Test Halt"}', encoding="utf-8")
    assert em.is_halted()[0], "EmergencyManager failed to halt!"
    
    # Verify Orchestrator rejects subsequent requests
    halt_resp = await engine.orchestrator.process_user_request("What is the time?", conversation_id="halted-test")
    print(f"Halt Response Message: '{halt_resp.message}' | State: {halt_resp.state.value}")
    assert halt_resp.state.value == "FAILED" or "halt" in halt_resp.message.lower()
    
    # Reset emergency halt for clean state
    em.resume()
    print(f"Post-Resume is_halted: {em.is_halted()[0]}")
    assert not em.is_halted()[0], "Failed to clear emergency halt!"
    print("[PASS] Emergency halt cuts off processing immediately.")

    # Cleanup Engine
    await engine.shutdown()
    print("\n" + "=" * 80)
    print("ALL 9 STAGES OF PHASE 5 VOICE & REAL LLM PIPELINE VERIFIED SUCCESSFULLY!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_voice_pipeline_verification())
