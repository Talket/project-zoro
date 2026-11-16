"""Voice Session Persistence and Privacy Management."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from zoro.storage.db import DatabaseManager
from zoro.voice.models import VoiceSession, VoiceUtterance

logger = logging.getLogger(__name__)


class VoiceSessionManager:
    """Manages voice session lifecycle and privacy-compliant database logging."""

    def __init__(self, db: DatabaseManager, store_transcripts: bool = True) -> None:
        self.db = db
        self.store_transcripts = store_transcripts
        self.active_session: Optional[VoiceSession] = None

    async def start_session(
        self,
        input_device: Optional[str] = None,
        output_device: Optional[str] = None,
        stt_provider: Optional[str] = None,
        tts_provider: Optional[str] = None,
    ) -> VoiceSession:
        """Create and persist a new voice session."""
        session_id = f"vses-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)
        session = VoiceSession(
            session_id=session_id,
            started_at=now,
            status="ACTIVE",
            input_device=input_device,
            output_device=output_device,
            stt_provider=stt_provider,
            tts_provider=tts_provider,
        )
        self.active_session = session

        await self.db.execute_write(
            """
            INSERT INTO voice_sessions (
                id, started_at, status, input_device, output_device, stt_provider, tts_provider
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.started_at.isoformat(),
                session.status,
                session.input_device,
                session.output_device,
                session.stt_provider,
                session.tts_provider,
            ),
        )
        logger.info("Voice session started: %s", session_id)
        return session

    async def record_utterance(
        self,
        transcript: str,
        duration_ms: float = 0.0,
        conversation_id: Optional[str] = None,
        message_id: Optional[str] = None,
        status: str = "RECOGNIZED",
    ) -> Optional[VoiceUtterance]:
        """Record utterance metadata without saving raw audio."""
        if not self.store_transcripts:
            return None

        session_id = self.active_session.session_id if self.active_session else "vses-adhoc"
        utt_id = f"vutt-{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        utterance = VoiceUtterance(
            id=utt_id,
            session_id=session_id,
            conversation_id=conversation_id,
            message_id=message_id,
            transcript=transcript,
            recognition_duration_ms=duration_ms,
            processing_status=status,
            created_at=now,
        )

        try:
            await self.db.execute_write(
                """
                INSERT INTO voice_utterances (
                    id, session_id, conversation_id, message_id, transcript,
                    language, recognition_duration_ms, processing_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    utterance.id,
                    utterance.session_id,
                    utterance.conversation_id,
                    utterance.message_id,
                    utterance.transcript,
                    utterance.language,
                    utterance.recognition_duration_ms,
                    utterance.processing_status,
                    utterance.created_at.isoformat(),
                ),
            )
        except Exception as e:
            logger.warning("Could not persist voice utterance to DB: %s", e)

        return utterance

    async def end_session(self, status: str = "COMPLETED", error: Optional[str] = None) -> None:
        """Close active voice session."""
        if not self.active_session:
            return

        now = datetime.now(timezone.utc)
        self.active_session.completed_at = now
        self.active_session.status = status
        self.active_session.error = error

        try:
            await self.db.execute_write(
                """
                UPDATE voice_sessions
                SET completed_at = ?, status = ?, error = ?
                WHERE id = ?
                """,
                (now.isoformat(), status, error, self.active_session.session_id),
            )
        except Exception as e:
            logger.warning("Could not update voice session in DB: %s", e)

        logger.info("Voice session ended: %s (%s)", self.active_session.session_id, status)
        self.active_session = None

    async def clear_history(self) -> int:
        """Purge stored voice session and utterance metadata for privacy."""
        await self.db.execute_write("DELETE FROM voice_utterances")
        await self.db.execute_write("DELETE FROM voice_metrics")
        await self.db.execute_write("DELETE FROM voice_sessions")
        logger.info("Cleared voice interaction history.")
        return 1
