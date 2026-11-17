"""Conversational Turn Taking and Orchestrator Integration Engine."""

from __future__ import annotations

import logging
import re
import uuid
from typing import AsyncIterator, Callable, List, Optional

from zoro.orchestrator.orchestrator import ZoroOrchestrator
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.tts.registry import TTSRegistry

logger = logging.getLogger(__name__)


class VoiceTurnManager:
    """Manages multi-turn conversation flow, context preservation, and orchestrator execution."""

    def __init__(
        self,
        orchestrator: ZoroOrchestrator,
        tts_registry: TTSRegistry,
        playback_manager: AudioPlaybackManager,
        session_manager: VoiceSessionManager,
    ) -> None:
        self.orchestrator = orchestrator
        self.tts = tts_registry
        self.playback = playback_manager
        self.session = session_manager
        self.active_conversation_id: str = f"vconv-{uuid.uuid4().hex[:12]}"

    def reset_conversation(self) -> None:
        """Reset conversation context for a new dialogue session."""
        self.active_conversation_id = f"vconv-{uuid.uuid4().hex[:12]}"
        logger.info("New voice conversation initialized: %s", self.active_conversation_id)

    async def execute_turn(
        self,
        user_transcript: str,
        on_text_generated: Optional[Callable[[str], None]] = None,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
    ) -> str:
        """Execute a full conversational turn from user speech to assistant spoken response."""
        clean_text = user_transcript.strip()
        if not clean_text:
            return ""

        logger.info("Executing voice turn for: '%s' (conv: %s)", clean_text, self.active_conversation_id)

        # 1. Record user utterance in session
        await self.session.record_utterance(
            transcript=clean_text,
            conversation_id=self.active_conversation_id,
            status="RECOGNIZED",
        )

        # 1b. Fast response for simple wake word greetings
        lower_clean = clean_text.lower().rstrip(".,!?")
        if lower_clean in ("zoro", "hey zoro", "hi zoro", "hello zoro"):
            reply_text = "I'm listening. How can I help you?"
            if on_text_generated:
                on_text_generated(reply_text)
            await self._speak_response(reply_text, on_audio_chunk)
            await self.session.record_utterance(
                transcript=reply_text,
                conversation_id=self.active_conversation_id,
                status="PROCESSED",
            )
            return reply_text

        # Strip wake prefix if user spoke "Zoro, <command>" in one breath
        prompt_text = clean_text
        for prefix in ("hey zoro,", "hey zoro", "zoro,", "zoro"):
            if prompt_text.lower().startswith(prefix):
                stripped = prompt_text[len(prefix):].strip().lstrip(",:- ")
                if stripped:
                    prompt_text = stripped
                break

        # 2. Dispatch to Central AI Orchestrator
        if hasattr(self.orchestrator, "process_request"):
            orch_res = await self.orchestrator.process_request(
                prompt=prompt_text,
                conversation_id=self.active_conversation_id,
            )
        elif hasattr(self.orchestrator, "process_user_request"):
            resp = await self.orchestrator.process_user_request(
                user_message=prompt_text,
                conversation_id=self.active_conversation_id,
            )
            orch_res = {
                "response": resp.message,
                "plan": resp.plan,
                "state": resp.state.value if hasattr(resp.state, "value") else str(resp.state),
            }
        else:
            orch_res = {"response": "Understood."}

        reply_text = orch_res.get("response", "")
        plan = orch_res.get("plan")
        state = orch_res.get("state")

        # Handle approval required state
        if state == "WAITING_FOR_APPROVAL":
            pending = orch_res.get("pending_approval", {})
            action = pending.get("action", "computer action")
            reply_text = f"I require your authorization to execute this sensitive operation: {action}. Please confirm in the dashboard."

        if not reply_text and plan:
            reply_text = "I have planned the task and will begin execution."

        if not reply_text:
            reply_text = "Understood."

        if on_text_generated:
            on_text_generated(reply_text)

        # 3. Stream spoken response sentence-by-sentence to TTS & Playback
        await self._speak_response(reply_text, on_audio_chunk)

        # 4. Record assistant utterance
        await self.session.record_utterance(
            transcript=reply_text,
            conversation_id=self.active_conversation_id,
            status="PROCESSED",
        )

        return reply_text

    async def _speak_response(
        self,
        full_text: str,
        on_audio_chunk: Optional[Callable[[bytes], None]] = None,
    ) -> None:
        """Split text into natural spoken sentences and synthesize with low latency."""
        sentences = self.split_sentences(full_text)
        for sentence in sentences:
            if not sentence.strip():
                continue
            try:
                pcm_bytes = await self.tts.synthesize(sentence)
                if pcm_bytes:
                    if on_audio_chunk:
                        on_audio_chunk(pcm_bytes)
                    self.playback.play_chunk(pcm_bytes)
            except Exception as e:
                logger.error("Error synthesizing voice response chunk: %s", e)

    @staticmethod
    def split_sentences(text: str) -> List[str]:
        """Split prose into conversational sentences for incremental TTS streaming."""
        # Split on sentence terminals (. ! ?) followed by whitespace or end of string
        parts = re.split(r"(?<=[.!?])\s+", text)
        return [p.strip() for p in parts if p.strip()]
