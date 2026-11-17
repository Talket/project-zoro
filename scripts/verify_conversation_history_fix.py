"""Verification script for conversation history window and voice enable/disable bug fix."""

import asyncio
import os
import sys
from pathlib import Path

# Ensure root is in python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from zoro.core.event_bus import AsyncEventBus
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
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.interruption import InterruptionManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.models import VoiceState
from zoro.voice.pipeline.voice_pipeline import VoicePipeline
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.vad.detector import VoiceActivityDetector
from zoro.voice.wake.wake_word import WakeWordDetector


async def main():
    print("=" * 60)
    print("VERIFYING MULTI-TURN CONVERSATION FIX (>10 TURNS) & VOICE TOGGLE")
    print("=" * 60)

    db_path = Path("reports/test_conv_fix.db")
    if db_path.exists():
        db_path.unlink()

    db = DatabaseManager(db_path=db_path)
    await db.initialize()

    sec_dir = Path("reports/test_sec")
    sec_dir.mkdir(parents=True, exist_ok=True)
    gate = PermissionGate()
    audit = AuditLogger(db=db, checkpoint_path=sec_dir / "audit.checkpoint", key=b"0" * 32)
    emergency_mgr = EmergencyManager(
        halt_lock_path=sec_dir / "halt.lock",
        pid_path=sec_dir / "zoro.pid",
    )
    tool_reg = ToolRegistry(db=db, audit=audit, permission_gate=gate)

    provider_reg = ProviderRegistry()
    ollama_prov = OllamaProvider(base_url="http://127.0.0.1:11434")
    provider_reg.register_provider("ollama", ollama_prov, default_model="qwen2.5:3b")
    provider_reg.set_active_provider("ollama")

    event_bus = AsyncEventBus()
    orch = ZoroOrchestrator(
        provider_registry=provider_reg,
        tool_registry=tool_reg,
        db=db,
        audit=audit,
        event_bus=event_bus,
        emergency_mgr=emergency_mgr,
    )

    conv_id = "test-conv-multi-turn"

    # Step 1: Execute 6 conversation turns (resulting in 12 messages > 10 limit)
    queries = [
        "What is 1 + 1?",
        "What is 2 + 2?",
        "What is 3 + 3?",
        "What is 4 + 4?",
        "What is 5 + 5?",
        "What was my first math question?",  # Turn 6: message count is now 11 before response
        "Are you still operational?",          # Turn 7: message count is now 13 before response
    ]

    print("\n--- Testing Multi-Turn Dialogue (> 10 messages) ---")
    for i, q in enumerate(queries, 1):
        print(f"\n[Turn {i}] User: '{q}'")
        res = await orch.process_user_request(user_message=q, conversation_id=conv_id)
        reply = res.message
        print(f"[Turn {i}] ZORO: '{reply[:90]}...'")
        assert reply != "I have processed your request, Sir.", (
            f"FAILED: Turn {i} returned the static fallback 'I have processed your request, Sir.'"
        )
        assert len(reply.strip()) > 0, f"FAILED: Turn {i} returned an empty response"

    # Verify message count in database
    rows = await db.execute_read(
        "SELECT count(*) FROM messages WHERE conversation_id = ?",
        (conv_id,),
    )
    total_msgs = rows[0][0]
    print(f"\n[PASS] Total persisted messages in conversation: {total_msgs} (exceeds 10-message window).")
    assert total_msgs >= 14, f"Expected at least 14 messages, got {total_msgs}"

    # Step 2: Test Voice Pipeline Enable -> Disable -> Enable
    print("\n--- Testing VoicePipeline Enable / Disable / Enable Cycle ---")
    capture = AudioCaptureManager()
    playback = AudioPlaybackManager()
    vad = VoiceActivityDetector()
    wake = WakeWordDetector()
    stt = STTRegistry()
    session_mgr = VoiceSessionManager(db=db)
    turn_mgr = VoiceTurnManager(
        orchestrator=orch,
        tts_registry=TTSRegistry(),
        playback_manager=playback,
        session_manager=session_mgr,
    )
    interruption = InterruptionManager(playback_manager=playback)

    pipeline = VoicePipeline(
        capture=capture,
        playback=playback,
        vad=vad,
        wake=wake,
        stt=stt,
        turn_manager=turn_mgr,
        interruption=interruption,
    )

    # 1. Enable pipeline
    pipeline.enable()
    assert pipeline.is_enabled is True
    assert pipeline.state == VoiceState.LISTENING

    # 2. Simulate injecting audio into buffer
    import numpy as np
    dummy_audio = np.ones(16000, dtype=np.int16) * 1000  # 1 second of audio
    capture.audio_buffer.write(dummy_audio)
    assert capture.audio_buffer.current_size_bytes > 0

    # 3. Disable pipeline
    pipeline.disable()
    assert pipeline.is_enabled is False
    assert pipeline.state == VoiceState.DISABLED
    assert capture.audio_buffer.current_size_bytes == 0, "Audio buffer was not flushed on disable!"

    # 4. Re-enable pipeline
    pipeline.enable()
    assert pipeline.is_enabled is True
    assert pipeline.state == VoiceState.LISTENING
    assert capture.audio_buffer.current_size_bytes == 0, "Audio buffer was not fresh on enable!"

    # 5. Clean teardown
    pipeline.disable()
    await db.close()

    print("\n[SUCCESS] All multi-turn conversation and voice lifecycle tests passed cleanly!")


if __name__ == "__main__":
    asyncio.run(main())
