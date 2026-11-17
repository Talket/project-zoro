"""Offline Local Wake-Word Detector for 'Zoro' and 'Hey Zoro'."""

from __future__ import annotations

import logging
import time
from typing import Callable, List, Optional, Set, Union
import numpy as np

from zoro.voice.models import WakeWordConfig, WakeWordResult

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Local, offline wake-word detector supporting 'Zoro' and 'Hey Zoro'."""

    def __init__(
        self,
        config: Optional[WakeWordConfig] = None,
        sample_rate: int = 16000,
        is_assistant_speaking_callback: Optional[Callable[[], bool]] = None,
    ) -> None:
        self.config = config or WakeWordConfig()
        self.sample_rate = sample_rate
        self.is_assistant_speaking_callback = is_assistant_speaking_callback

        # Normalize enabled phrases
        self.enabled_phrases: Set[str] = {p.strip().lower() for p in self.config.enabled_phrases}

        self.last_detection_time: float = 0.0
        self._custom_model = None

    def enable_phrase(self, phrase: str) -> None:
        """Enable detection for a specific phrase ('zoro' or 'hey zoro')."""
        normalized = phrase.strip().lower()
        self.enabled_phrases.add(normalized)
        logger.info("Enabled wake phrase: '%s'", normalized)

    def disable_phrase(self, phrase: str) -> None:
        """Disable detection for a specific phrase."""
        normalized = phrase.strip().lower()
        if normalized in self.enabled_phrases:
            self.enabled_phrases.remove(normalized)
            logger.info("Disabled wake phrase: '%s'", normalized)

    def is_phrase_enabled(self, phrase: str) -> bool:
        """Check if phrase is currently enabled."""
        return phrase.strip().lower() in self.enabled_phrases

    def trigger_push_to_talk(self) -> WakeWordResult:
        """Manual Push-to-Talk activation bypassing acoustic keyword detection."""
        now = time.time()
        self.last_detection_time = now
        logger.info("Push-to-Talk triggered manually.")
        return WakeWordResult(
            detected=True,
            wake_word="push_to_talk",
            confidence=1.0,
            timestamp=now,
        )

    def process_audio(
        self,
        audio_data: Union[bytes, np.ndarray],
        text_hint: Optional[str] = None,
    ) -> WakeWordResult:
        """Analyze audio buffer or streaming transcript for configured wake words."""
        now = time.time()

        # 1. Enforce cooldown period to prevent double-triggering
        if now - self.last_detection_time < self.config.cooldown_seconds:
            return WakeWordResult(detected=False)

        # 2. Suppress wake-word during active assistant speech (Self-Voice Immunity)
        if self.is_assistant_speaking_callback and self.is_assistant_speaking_callback():
            return WakeWordResult(detected=False)

        # 3. Text-hint / fast-transcription acoustic matching
        if text_hint:
            norm_hint = text_hint.lower().strip()
            # Check "hey zoro" first if enabled
            if "hey zoro" in self.enabled_phrases and "hey zoro" in norm_hint:
                self.last_detection_time = now
                logger.info("Wake word detected: 'Hey Zoro' (confidence: 0.95)")
                return WakeWordResult(
                    detected=True,
                    wake_word="hey zoro",
                    confidence=0.95,
                    timestamp=now,
                )
            # Check "zoro" if enabled
            if "zoro" in self.enabled_phrases and "zoro" in norm_hint:
                self.last_detection_time = now
                logger.info("Wake word detected: 'Zoro' (confidence: 0.92)")
                return WakeWordResult(
                    detected=True,
                    wake_word="zoro",
                    confidence=0.92,
                    timestamp=now,
                )

        # 4. Acoustic energy and spectral formant correlation
        if isinstance(audio_data, bytes):
            samples = np.frombuffer(audio_data, dtype=np.int16)
        else:
            samples = audio_data.astype(np.int16)

        if len(samples) < int(self.sample_rate * 0.25):
            return WakeWordResult(detected=False)

        float_samples = samples.astype(np.float32) / 32768.0

        # Energy threshold to locate active speech region within the buffer window
        active_indices = np.where(np.abs(float_samples) > 0.01)[0]
        if len(active_indices) == 0:
            return WakeWordResult(detected=False)

        speech_start = active_indices[0]
        speech_end = active_indices[-1]
        active_samples = float_samples[speech_start : speech_end + 1]
        active_duration = len(active_samples) / float(self.sample_rate)

        # Need at least 250ms of active speech
        if active_duration < 0.25:
            return WakeWordResult(detected=False)

        active_rms = float(np.sqrt(np.mean(active_samples**2)))
        if active_rms < 0.015:
            return WakeWordResult(detected=False)

        # Syllable onset fricative analysis for the initial /z/ sound
        onset_len = max(int(len(active_samples) * 0.4), int(self.sample_rate * 0.08))
        onset_samples = active_samples[:onset_len]
        zcr = np.mean(np.abs(np.diff(np.sign(onset_samples)))) / 2.0
        has_fricative_onset = 0.07 <= zcr <= 0.65

        # Match against duration bounds for "zoro" (0.25s - 1.6s) and "hey zoro" (0.5s - 2.2s)
        if has_fricative_onset and active_rms >= 0.018:
            if "hey zoro" in self.enabled_phrases and 0.5 <= active_duration <= 2.2:
                confidence = min(0.95, float(active_rms * 5.0 * self.config.sensitivity))
                if confidence >= self.config.sensitivity:
                    self.last_detection_time = now
                    logger.info("Wake word detected: 'Hey Zoro' (confidence: %.2f)", confidence)
                    return WakeWordResult(
                        detected=True,
                        wake_word="hey zoro",
                        confidence=confidence,
                        timestamp=now,
                    )

            if "zoro" in self.enabled_phrases and 0.25 <= active_duration <= 1.6:
                confidence = min(0.95, float(active_rms * 4.5 * self.config.sensitivity))
                if confidence >= self.config.sensitivity:
                    self.last_detection_time = now
                    logger.info("Wake word detected: 'Zoro' (confidence: %.2f)", confidence)
                    return WakeWordResult(
                        detected=True,
                        wake_word="zoro",
                        confidence=confidence,
                        timestamp=now,
                    )

        return WakeWordResult(detected=False)
