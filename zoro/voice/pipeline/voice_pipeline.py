"""Asynchronous Real-Time Voice Processing Pipeline."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, List, Optional

from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.interruption import InterruptionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.models import PipelineMetrics, VoiceState
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.vad.detector import VoiceActivityDetector
from zoro.voice.wake.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)


class VoicePipeline:
    """Coordinates end-to-end streaming audio flow across VAD, Wake Word, STT, LLM, and TTS."""

    def __init__(
        self,
        capture: AudioCaptureManager,
        playback: AudioPlaybackManager,
        vad: VoiceActivityDetector,
        wake: WakeWordDetector,
        stt: STTRegistry,
        turn_manager: VoiceTurnManager,
        interruption: InterruptionManager,
        on_state_change: Optional[Callable[[VoiceState], None]] = None,
    ) -> None:
        self.capture = capture
        self.playback = playback
        self.vad = vad
        self.wake = wake
        self.stt = stt
        self.turn_manager = turn_manager
        self.interruption = interruption
        self.on_state_change = on_state_change

        self._state: VoiceState = VoiceState.IDLE
        self._is_enabled: bool = False
        self._is_listening: bool = True
        self._utterance_frames: List[bytes] = []
        self._collecting_utterance: bool = False
        self._pipeline_task: Optional[asyncio.Task] = None
        self._metrics = PipelineMetrics()

        # Connect audio frame callback
        self.capture.register_callback(self._on_audio_frame)

        # Connect interruption callback
        self.interruption.register_callback(self._on_interrupted)

        # Connect playback finished callback
        self.playback.register_on_finished(self._on_playback_finished)

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    @property
    def is_listening(self) -> bool:
        return self._is_listening

    @property
    def metrics(self) -> PipelineMetrics:
        return self._metrics

    def set_state(self, new_state: VoiceState) -> None:
        if self._state != new_state:
            self._state = new_state
            logger.debug("VoicePipeline state -> %s", new_state.value)
            if self.on_state_change:
                try:
                    self.on_state_change(new_state)
                except Exception as e:
                    logger.error("Error in on_state_change callback: %s", e)

    def enable(self) -> None:
        """Enable voice interaction pipeline."""
        self._is_enabled = True
        self.capture.start_capture()
        self.set_state(VoiceState.LISTENING if self._is_listening else VoiceState.IDLE)
        logger.info("VoicePipeline enabled.")

    def disable(self) -> None:
        """Disable voice interaction pipeline."""
        self._is_enabled = False
        self.playback.stop_playback()
        self.capture.stop_capture()
        self._collecting_utterance = False
        self._utterance_frames.clear()
        self.set_state(VoiceState.DISABLED)
        logger.info("VoicePipeline disabled.")

    def set_listening(self, listening: bool) -> None:
        """Toggle active microphone listening for wake-word / speech."""
        self._is_listening = listening
        if self._is_enabled:
            self.set_state(VoiceState.LISTENING if listening else VoiceState.IDLE)

    def trigger_push_to_talk(self) -> None:
        """Manually trigger push-to-talk activation."""
        if not self._is_enabled:
            self.enable()

        wake_res = self.wake.trigger_push_to_talk()
        if wake_res.detected:
            self._on_wake_detected(wake_res.wake_word or "push_to_talk")

    def _on_audio_frame(self, pcm_bytes: bytes, rms: float) -> None:
        """Invoked on each microphone audio frame (~20ms)."""
        if not self._is_enabled:
            return

        # 1. Barge-in detection during playback
        if self.playback.is_playing:
            self.interruption.check_audio_frame(pcm_bytes)
            return

        # 2. VAD processing
        vad_res = self.vad.process_frame(pcm_bytes)

        # 3. If currently collecting an active speech utterance
        if self._collecting_utterance:
            self._utterance_frames.append(pcm_bytes)
            if vad_res.speech_ended or len(self._utterance_frames) > 750:  # ~15 seconds max
                self._collecting_utterance = False
                audio_payload = b"".join(self._utterance_frames)
                self._utterance_frames.clear()
                self._dispatch_transcription(audio_payload)
            return

        # 4. If listening for wake word
        if self._is_listening and self._state in (VoiceState.IDLE, VoiceState.LISTENING):
            # Pass recent audio to wake detector
            recent_audio = self.capture.audio_buffer.get_recent(1.5)
            wake_res = self.wake.process_audio(recent_audio)
            if wake_res.detected:
                self._on_wake_detected(wake_res.wake_word or "zoro")

    def _on_wake_detected(self, wake_phrase: str) -> None:
        logger.info("Wake word activated pipeline: '%s'", wake_phrase)
        self.set_state(VoiceState.WAKE_DETECTED)
        self._collecting_utterance = True
        self._utterance_frames.clear()

        # Seed utterance buffer with recent pre-wake audio to prevent cutting off first syllable
        pre_audio = self.capture.audio_buffer.get_recent(0.5)
        if len(pre_audio) > 0:
            self._utterance_frames.append(pre_audio.tobytes())

    def _dispatch_transcription(self, audio_bytes: bytes) -> None:
        """Dispatch speech-to-text and turn processing asynchronously."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._process_utterance(audio_bytes))
        except RuntimeError:
            # No running loop, run in separate thread
            asyncio.run(self._process_utterance(audio_bytes))

    async def _process_utterance(self, audio_bytes: bytes) -> None:
        """Execute STT and conversation turn."""
        turn_start = time.perf_counter()
        self.set_state(VoiceState.TRANSCRIBING)

        try:
            stt_start = time.perf_counter()
            stt_res = await self.stt.transcribe(audio_bytes)
            self._metrics.stt_latency_ms = (time.perf_counter() - stt_start) * 1000.0

            transcript = stt_res.transcript.strip()
            if not transcript:
                logger.info("No audible transcript recognized.")
                self.set_state(VoiceState.LISTENING if self._is_listening else VoiceState.IDLE)
                return

            logger.info("Voice Recognized: '%s'", transcript)
            self.set_state(VoiceState.THINKING)

            think_start = time.perf_counter()
            self.set_state(VoiceState.SPEAKING)

            reply = await self.turn_manager.execute_turn(transcript)
            self._metrics.ttft_ms = (time.perf_counter() - think_start) * 1000.0
            self._metrics.total_turnaround_ms = (time.perf_counter() - turn_start) * 1000.0
            logger.info("Voice turn completed. Total turnaround: %.1f ms", self._metrics.total_turnaround_ms)

        except Exception as e:
            logger.error("Error processing voice utterance: %s", e)
            self.set_state(VoiceState.ERROR)
            await asyncio.sleep(1.0)
            self.set_state(VoiceState.LISTENING if self._is_listening else VoiceState.IDLE)

    def _on_interrupted(self, reason: str) -> None:
        logger.info("Pipeline received interruption: %s", reason)
        self.set_state(VoiceState.INTERRUPTED)
        self._collecting_utterance = False
        self._utterance_frames.clear()

    def _on_playback_finished(self) -> None:
        if self._state == VoiceState.SPEAKING:
            self.set_state(VoiceState.LISTENING if self._is_listening else VoiceState.IDLE)
