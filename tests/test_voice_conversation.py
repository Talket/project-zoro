"""Unit and integration tests for Voice Conversation Subsystem (Sessions, Turns, Interruption)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.interruption import InterruptionManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.models import VoiceSession, VoiceUtterance
from zoro.voice.tts.mock import MockTTSProvider
from zoro.voice.tts.registry import TTSRegistry


@pytest.mark.asyncio
async def test_voice_session_manager(test_db):
    """Verify VoiceSessionManager session lifecycle and DB storage."""
    mgr = VoiceSessionManager(db=test_db, store_transcripts=True)

    session = await mgr.start_session(
        input_device="Microphone Array",
        output_device="Speakers",
        stt_provider="faster-whisper",
        tts_provider="windows-sapi",
    )
    assert session.session_id.startswith("vses-")
    assert session.status == "ACTIVE"

    # Record utterances
    utt1 = await mgr.record_utterance("Open File Explorer", duration_ms=120.0)
    assert utt1 is not None
    assert utt1.transcript == "Open File Explorer"

    utt2 = await mgr.record_utterance("Opening Explorer now.", duration_ms=45.0, status="PROCESSED")
    assert utt2 is not None

    # End session
    await mgr.end_session(status="COMPLETED")
    assert mgr.active_session is None

    # Test clear_history
    cleared = await mgr.clear_history()
    assert cleared == 1


@pytest.mark.asyncio
async def test_voice_session_privacy_opt_out(test_db):
    """Verify that when store_transcripts is False, utterances are not recorded."""
    mgr = VoiceSessionManager(db=test_db, store_transcripts=False)
    await mgr.start_session()

    utt = await mgr.record_utterance("Confidential user speech")
    assert utt is None
    await mgr.end_session()


def test_interruption_manager():
    """Verify barge-in keyword and audio detection."""
    mock_playback = MagicMock(spec=AudioPlaybackManager)
    mock_playback.is_playing = False

    interruption_events = []
    mgr = InterruptionManager(mock_playback, interruption_energy_threshold=0.05)
    mgr.register_callback(lambda reason: interruption_events.append(reason))

    # When not playing, stop keyword does not trigger barge-in
    assert mgr.check_text_interruption("stop") is False
    assert len(interruption_events) == 0

    # When playing, stop keyword triggers immediate stop
    mock_playback.is_playing = True
    assert mgr.check_text_interruption("Zoro stop speaking please") is True
    assert mock_playback.stop_playback.called
    assert len(interruption_events) == 1
    assert "keyword:stop" in interruption_events[0]

    # Test "cancel" keyword
    assert mgr.check_text_interruption("cancel that") is True
    assert "keyword:cancel" in interruption_events[1]

    # Test "quiet" keyword
    assert mgr.check_text_interruption("be quiet") is True
    assert "keyword:quiet" in interruption_events[2]

    # Test audio frame interruption
    mgr._last_interruption_time = 0.0
    import numpy as np
    loud_frame = (np.ones(320, dtype=np.int16) * 15000).tobytes()
    assert mgr.check_audio_frame(loud_frame) is True


@pytest.mark.asyncio
async def test_voice_turn_manager(test_db):
    """Verify multi-turn flow, sentence splitting, and orchestrator integration."""
    session_mgr = VoiceSessionManager(db=test_db, store_transcripts=True)
    await session_mgr.start_session()

    tts_registry = TTSRegistry(default_provider="mock")
    mock_playback = MagicMock(spec=AudioPlaybackManager)

    # Mock Orchestrator
    mock_orchestrator = MagicMock()
    mock_orchestrator.process_request = AsyncMock(return_value={
        "status": "COMPLETED",
        "response": "Here is the information you requested. Everything is in order.",
    })

    turn_mgr = VoiceTurnManager(
        orchestrator=mock_orchestrator,
        tts_registry=tts_registry,
        playback_manager=mock_playback,
        session_manager=session_mgr,
    )

    generated_texts = []
    response = await turn_mgr.execute_turn(
        user_transcript="What is the weather?",
        on_text_generated=lambda t: generated_texts.append(t),
    )

    assert "Here is the information" in response
    assert len(generated_texts) == 1
    # Check that speech was played
    assert mock_playback.play_chunk.called

    # Test sentence splitting
    sentences = VoiceTurnManager.split_sentences("First sentence. Second sentence! Third sentence? Done.")
    assert len(sentences) == 4
    assert sentences[0] == "First sentence."
    assert sentences[1] == "Second sentence!"
    assert sentences[2] == "Third sentence?"
    assert sentences[3] == "Done."


@pytest.mark.asyncio
async def test_voice_turn_manager_approval_state(test_db):
    """Verify approval required state generates appropriate speech warning."""
    session_mgr = VoiceSessionManager(db=test_db, store_transcripts=True)
    await session_mgr.start_session()

    tts_registry = TTSRegistry(default_provider="mock")
    mock_playback = MagicMock(spec=AudioPlaybackManager)

    # Mock Orchestrator returning WAITING_FOR_APPROVAL
    mock_orchestrator = MagicMock()
    mock_orchestrator.process_request = AsyncMock(return_value={
        "status": "WAITING_FOR_APPROVAL",
        "state": "WAITING_FOR_APPROVAL",
        "pending_approval": {"action": "delete temporary files"},
    })

    turn_mgr = VoiceTurnManager(
        orchestrator=mock_orchestrator,
        tts_registry=tts_registry,
        playback_manager=mock_playback,
        session_manager=session_mgr,
    )

    response = await turn_mgr.execute_turn(user_transcript="Delete old logs")
    assert "require your authorization" in response
    assert "delete temporary files" in response
