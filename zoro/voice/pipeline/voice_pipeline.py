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
        on_transcription: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.capture = capture
        self.playback = playback
        self.vad = vad
        self.wake = wake
        self.stt = stt
        self.turn_manager = turn_manager
        self.interruption = interruption
        self.on_state_change = on_state_change
        self.on_transcription = on_transcription

        self._state: VoiceState = VoiceState.IDLE
        self._is_enabled: bool = False
        self._is_listening: bool = True
        self._utterance_frames: List[bytes] = []
        self._collecting_utterance: bool = False
        self._pipeline_task: Optional[asyncio.Task] = None
        self._metrics = PipelineMetrics()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._followup_until: float = 0.0

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Assign the primary engine event loop for thread-safe cross-thread scheduling."""
        self._loop = loop

        # Connect audio frame callback
        self.capture.register_callback(self._on_audio_frame)

        # Connect interruption callback
        self.interruption.register_callback(self._on_interrupted)

        # Connect playback started & finished callbacks
        self.playback.register_on_started(self._on_playback_started)
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

        # 4. If listening for wake word or in active conversational follow-up
        if self._is_listening and self._state in (VoiceState.IDLE, VoiceState.LISTENING):
            now = time.time()
            if now < self._followup_until and (vad_res.speech_onset or (vad_res.is_speech and rms > 0.015)):
                self._followup_until = 0.0
                self._on_wake_detected("follow_up")
                return

            # Pass recent audio to wake detector (2.0s window for full wake phrases)
            recent_audio = self.capture.audio_buffer.get_recent(2.0)
            if len(recent_audio) > 0:
                wake_res = self.wake.process_audio(recent_audio)
                if wake_res.detected:
                    self._on_wake_detected(wake_res.wake_word or "zoro")

    def _on_wake_detected(self, wake_phrase: str) -> None:
        logger.info("Wake word activated pipeline: '%s'", wake_phrase)
        self.set_state(VoiceState.WAKE_DETECTED)
        self._collecting_utterance = True
        self._utterance_frames.clear()
        if self.on_transcription:
            self.on_transcription(f"[Wake Word: '{wake_phrase}']", "system")

        # Seed utterance buffer with recent pre-wake audio to prevent cutting off first syllable
        pre_audio = self.capture.audio_buffer.get_recent(0.5)
        if len(pre_audio) > 0:
            self._utterance_frames.append(pre_audio.tobytes())

    def _dispatch_transcription(self, audio_bytes: bytes) -> None:
        """Dispatch speech-to-text and turn processing asynchronously onto the engine event loop."""
        target_loop = self._loop
        if target_loop is None or not target_loop.is_running():
            try:
                target_loop = asyncio.get_running_loop()
            except RuntimeError:
                target_loop = None

        if target_loop and target_loop.is_running():
            try:
                running_now = asyncio.get_running_loop()
            except RuntimeError:
                running_now = None

            if running_now is target_loop:
                target_loop.create_task(self._process_utterance(audio_bytes))
            else:
                asyncio.run_coroutine_threadsafe(self._process_utterance(audio_bytes), target_loop)
        else:
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
            if self.on_transcription:
                self.on_transcription(transcript, "user")
            self.set_state(VoiceState.THINKING)

            think_start = time.perf_counter()

            reply = await asyncio.wait_for(
                self.turn_manager.execute_turn(
                    transcript,
                    on_text_generated=lambda txt: self.on_transcription(txt, "zoro") if self.on_transcription else None,
                ),
                timeout=30.0,
            )
            self._metrics.ttft_ms = (time.perf_counter() - think_start) * 1000.0
            self._metrics.total_turnaround_ms = (time.perf_counter() - turn_start) * 1000.0
            logger.info("Voice turn completed. Total turnaround: %.1f ms", self._metrics.total_turnaround_ms)

            # If the turn was a wake greeting, extend conversational follow-up window
            if reply and any(k in reply.lower() for k in ("listening", "help you", "how can i")):
                self._followup_until = time.time() + 7.0

            # If playback did not start or already finished before execute_turn returned
            if not self.playback.is_playing and self._state == VoiceState.THINKING:
                self.set_state(VoiceState.LISTENING if self._is_listening else VoiceState.IDLE)

        except asyncio.TimeoutError:
            logger.error("Voice turn processing timed out after 30 seconds.")
            self.set_state(VoiceState.ERROR)
            await asyncio.sleep(1.0)
            self.set_state(VoiceState.LISTENING if self._is_listening else VoiceState.IDLE)
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

    def _on_playback_started(self) -> None:
        """Invoked when speaker audio physically begins playing."""
        self.set_state(VoiceState.SPEAKING)

    def _on_playback_finished(self) -> None:
        if self._state == VoiceState.SPEAKING:
            self.set_state(VoiceState.LISTENING if self._is_listening else VoiceState.IDLE)
