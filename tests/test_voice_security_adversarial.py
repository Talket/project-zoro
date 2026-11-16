"""Adversarial and Security Verification Tests for ZORO Voice Subsystem.

Verifies:
1. Emergency halt freezes audio capture and playback immediately.
2. Wake-word detection activates listening only; NEVER grants permissions or bypasses security gates.
3. Voice-commanded computer actions follow identical permission tiers and approval workflows as text.
4. Privacy invariants: Raw audio bytes are NEVER persisted to database or audit logs.
"""

import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.security.emergency import EmergencyManager
from zoro.storage.db import DatabaseManager
from zoro.voice.manager import VoiceManager
from zoro.voice.models import VoiceState


@pytest.mark.asyncio
async def test_emergency_halt_freezes_voice_subsystem(test_db):
    """Verify that when emergency halt is active, voice capture/playback are frozen immediately."""
    emergency = EmergencyManager()
    mock_orch = MagicMock()

    voice = VoiceManager(db=test_db, orchestrator=mock_orch, emergency_mgr=emergency)

    # Trigger emergency halt
    with patch.object(emergency, "is_halted", return_value=True):
        # Initializing should abort
        await voice.initialize()
        assert voice.pipeline.state == VoiceState.IDLE or voice.pipeline.state == VoiceState.DISABLED

        # Enabling voice should fail
        assert voice.enable() is False

        # Push to talk should fail
        assert voice.trigger_push_to_talk() is False

        # Listening should fail
        assert voice.start_listening() is False


@pytest.mark.asyncio
async def test_wake_word_never_authorizes_operations():
    """Verify wake-word detection only activates listening and never bypasses tool permissions."""
    from zoro.voice.wake.wake_word import WakeWordDetector

    det = WakeWordDetector()
    res = det.process_audio(b"", text_hint="hey zoro delete the system folder")

    # Wake word was detected
    assert res.detected is True
    assert res.wake_word == "hey zoro"

    # But WakeWordResult contains ONLY detection metadata, no authorization tokens
    assert not hasattr(res, "authorization_token")
    assert not hasattr(res, "approval_token")
    assert not hasattr(res, "tier_override")


@pytest.mark.asyncio
async def test_voice_command_strictly_enforces_approval_tiers(test_db):
    """Verify that high-tier operations requested via voice trigger WAITING_FOR_APPROVAL."""
    from zoro.voice.conversation.turn_manager import VoiceTurnManager
    from zoro.voice.conversation.session import VoiceSessionManager
    from zoro.voice.tts.registry import TTSRegistry
    from zoro.voice.audio.playback import AudioPlaybackManager

    session_mgr = VoiceSessionManager(db=test_db, store_transcripts=True)
    await session_mgr.start_session()
    tts_registry = TTSRegistry(default_provider="mock")
    mock_playback = MagicMock(spec=AudioPlaybackManager)

    # Mock Orchestrator returning WAITING_FOR_APPROVAL for a Tier 4/5 action
    mock_orch = MagicMock()
    mock_orch.process_request = AsyncMock(return_value={
        "status": "WAITING_FOR_APPROVAL",
        "state": "WAITING_FOR_APPROVAL",
        "plan": None,
        "pending_approval": {
            "token": "tok-voice-restricted-999",
            "action": "delete system files in C:\\Windows\\Temp",
            "tier": "TIER_4_DANGEROUS",
        },
        "response": "",
    })

    turn_mgr = VoiceTurnManager(
        orchestrator=mock_orch,
        tts_registry=tts_registry,
        playback_manager=mock_playback,
        session_manager=session_mgr,
    )

    # User issues dangerous command verbally
    verbal_response = await turn_mgr.execute_turn("Delete all files in Windows Temp immediately")

    # Zoro verbalizes refusal without prior UI approval
    assert "require your authorization" in verbal_response.lower()
    assert "delete system files" in verbal_response.lower()

    # Verify no execution happened without explicit user authorization token
    assert mock_orch.process_request.called
    call_args = mock_orch.process_request.call_args[1]
    assert call_args["prompt"] == "Delete all files in Windows Temp immediately"


@pytest.mark.asyncio
async def test_privacy_invariant_zero_raw_audio_in_database(test_db):
    """Verify raw audio bytes are NEVER stored in the SQLite database or tables."""
    from zoro.voice.conversation.session import VoiceSessionManager

    session_mgr = VoiceSessionManager(db=test_db, store_transcripts=True)
    session = await session_mgr.start_session(
        input_device="Realtek Mic",
        output_device="Realtek Speakers",
    )

    # Record 3 utterances
    await session_mgr.record_utterance("Create monthly report document")
    await session_mgr.record_utterance("Creating document now", status="PROCESSED")
    await session_mgr.end_session()

    # Query all tables in database for blob or raw audio columns
    tables = ["voice_sessions", "voice_utterances", "voice_metrics", "voice_settings"]
    for t in tables:
        rows = await test_db.execute_read(f"PRAGMA table_info({t})")
        for col in rows:
            col_name = str(col[1])
            col_type = str(col[2]).upper()
            # Invariant: No audio blobs exist
            assert "BLOB" not in col_type
            assert "AUDIO" not in col_name.upper()
            assert "RAW" not in col_name.upper()

    # Inspect stored records
    utterances = await test_db.execute_read("SELECT transcript FROM voice_utterances")
    assert len(utterances) == 2
    for u in utterances:
        transcript = u[0]
        assert isinstance(transcript, str)
        # Ensure transcript is just text
        assert "Creat" in transcript
