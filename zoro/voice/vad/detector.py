"""Voice Activity Detection using WebRTC VAD with Energy-Based Fallback."""

from __future__ import annotations

import logging
import time
from typing import Optional
import numpy as np

from zoro.voice.models import VADConfig, VADResult

logger = logging.getLogger(__name__)

try:
    import webrtcvad
    WEBRTC_AVAILABLE = True
except ImportError:
    WEBRTC_AVAILABLE = False


class VoiceActivityDetector:
    """Detects speech onset, speech presence, and speech termination in real-time audio."""

    def __init__(self, config: Optional[VADConfig] = None, sample_rate: int = 16000) -> None:
        self.config = config or VADConfig()
        self.sample_rate = sample_rate
        self.vad_engine = None

        if WEBRTC_AVAILABLE and sample_rate in (8000, 16000, 32000, 48000):
            try:
                self.vad_engine = webrtcvad.Vad(self.config.aggressiveness)
            except Exception as e:
                logger.warning("Could not initialize webrtcvad (%s), using energy fallback.", e)
                self.vad_engine = None

        self._in_speech = False
        self._speech_onset_start: Optional[float] = None
        self._silence_start: Optional[float] = None

    def reset(self) -> None:
        """Reset internal speech state."""
        self._in_speech = False
        self._speech_onset_start = None
        self._silence_start = None

    def process_frame(self, pcm_bytes: bytes) -> VADResult:
        """Process a 10ms, 20ms, or 30ms PCM int16 audio frame."""
        now = time.time()
        samples = np.frombuffer(pcm_bytes, dtype=np.int16)
        if len(samples) == 0:
            return VADResult(is_speech=False, energy=0.0)

        # Compute RMS energy
        float_samples = samples.astype(np.float32) / 32768.0
        energy = float(np.sqrt(np.mean(float_samples**2)))

        # Determine frame speech status
        is_speech = False
        confidence = 0.0

        if self.vad_engine is not None and len(pcm_bytes) in (160, 320, 480, 640, 960, 1920):
            try:
                # Energy floor gating: pure silence or below-threshold energy is never speech
                if energy < self.config.energy_threshold:
                    is_speech = False
                    confidence = 0.0
                else:
                    is_speech = self.vad_engine.is_speech(pcm_bytes, self.sample_rate)
                    confidence = 0.9 if is_speech else 0.1
            except Exception:
                is_speech = energy > self.config.energy_threshold
                confidence = min(1.0, energy * 10.0)
        else:
            is_speech = energy > self.config.energy_threshold
            confidence = min(1.0, energy * 10.0)

        # Track speech onset and termination
        speech_onset = False
        speech_ended = False

        if is_speech:
            self._silence_start = None
            if not self._in_speech:
                if self._speech_onset_start is None:
                    self._speech_onset_start = now
                elif now - self._speech_onset_start >= self.config.speech_onset_threshold_sec:
                    self._in_speech = True
                    speech_onset = True
                    self._speech_onset_start = None
        else:
            self._speech_onset_start = None
            if self._in_speech:
                if self._silence_start is None:
                    self._silence_start = now
                elif now - self._silence_start >= self.config.silence_duration_threshold_sec:
                    self._in_speech = False
                    speech_ended = True
                    self._silence_start = None

        return VADResult(
            is_speech=self._in_speech,
            confidence=confidence,
            speech_onset=speech_onset,
            speech_ended=speech_ended,
            energy=energy,
        )
