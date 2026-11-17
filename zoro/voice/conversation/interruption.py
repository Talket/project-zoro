"""Barge-In Interruption Detection and Playback Cancellation Engine."""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional
import numpy as np

from zoro.voice.audio.playback import AudioPlaybackManager

logger = logging.getLogger(__name__)

INTERRUPTION_KEYWORDS = {
    "stop",
    "cancel",
    "hold on",
    "wait",
    "pause",
    "quiet",
    "shush",
    "shut up",
    "enough",
}


class InterruptionManager:
    """Detects barge-in speech and immediately cancels active assistant audio playback."""

    def __init__(
        self,
        playback_manager: AudioPlaybackManager,
        interruption_energy_threshold: float = 0.18,
    ) -> None:
        self.playback = playback_manager
        self.interruption_energy_threshold = interruption_energy_threshold
        self._on_interrupted_callbacks: List[Callable[[str], None]] = []
        self._last_interruption_time: float = 0.0
        self._playback_start_time: float = 0.0
        self._consecutive_loud_frames: int = 0

        # Automatically bind playback lifecycle events
        self.playback.register_on_started(self.on_playback_started)
        self.playback.register_on_finished(self.on_playback_finished)

    def on_playback_started(self) -> None:
        """Invoked when speaker audio physically begins playing."""
        self._playback_start_time = time.time()
        self._consecutive_loud_frames = 0

    def on_playback_finished(self) -> None:
        """Invoked when speaker audio playback terminates or is stopped."""
        self._consecutive_loud_frames = 0

    def register_callback(self, callback: Callable[[str], None]) -> None:
        if callback not in self._on_interrupted_callbacks:
            self._on_interrupted_callbacks.append(callback)

    def check_text_interruption(self, text: str) -> bool:
        """Check if incoming transcript is an explicit stop/cancel command during playback."""
        if not self.playback.is_playing:
            return False

        norm = text.lower().strip()
        matched = None
        for kw in INTERRUPTION_KEYWORDS:
            if kw in norm:
                matched = kw
                break

        if matched:
            logger.info("Barge-in interruption triggered by keyword: '%s'", matched)
            self._trigger_interruption(f"keyword:{matched}")
            return True

        return False

    def check_audio_frame(self, pcm_bytes: bytes) -> bool:
        """Check if incoming microphone frame represents an intentional barge-in utterance."""
        if not self.playback.is_playing:
            self._consecutive_loud_frames = 0
            return False

        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(samples) == 0:
            return False

        now = time.time()
        # Onset immunity window: prevent speaker acoustic echo from instantly aborting playback as soon as audio starts
        if self._playback_start_time > 0 and (now - self._playback_start_time < 0.6):
            return False

        float_samples = samples.astype(np.float32) / 32768.0
        energy = float(np.sqrt(np.mean(float_samples**2)))

        # Intentional barge-in speech: immediate trigger on high energy (>=0.35) or sustained speech (>=2 frames)
        if energy > self.interruption_energy_threshold:
            self._consecutive_loud_frames += 1
            if energy >= 0.35 or self._consecutive_loud_frames >= 2:
                if now - self._last_interruption_time > 1.0:
                    logger.info("Barge-in speech onset detected during playback (energy: %.3f)", energy)
                    self._trigger_interruption("speech_onset")
                    self._consecutive_loud_frames = 0
                    return True
        else:
            self._consecutive_loud_frames = 0

        return False

    def _trigger_interruption(self, reason: str) -> None:
        self._last_interruption_time = time.time()
        self.playback.stop_playback()

        for cb in self._on_interrupted_callbacks:
            try:
                cb(reason)
            except Exception as e:
                logger.error("Error in interruption callback: %s", e)
