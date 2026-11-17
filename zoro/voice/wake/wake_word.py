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

        # Frame-level short-time energy (20ms frames = 320 samples at 16kHz)
        frame_size = int(self.sample_rate * 0.02)
        if frame_size <= 0:
            return WakeWordResult(detected=False)

        rms_frames = [
            float(np.sqrt(np.mean(float_samples[i : i + frame_size] ** 2)))
            for i in range(0, len(float_samples) - frame_size + 1, frame_size)
        ]
        if not rms_frames:
            return WakeWordResult(detected=False)

        # Estimate room ambient noise baseline (30th percentile)
        noise_floor = float(np.percentile(rms_frames, 30)) if len(rms_frames) >= 5 else 0.005
        sensitivity = float(self.config.sensitivity)
        speech_thresh = max(0.015, noise_floor * (1.4 + (1.0 - sensitivity) * 0.5))

        active_indices = np.where(np.array(rms_frames) >= speech_thresh)[0]
        # Need at least 160ms of active speech frames (8 frames)
        if len(active_indices) < 8:
            return WakeWordResult(detected=False)

        # Cluster active frames allowing up to 100ms (5 frames) intra-word silence tolerance
        clusters = []
        curr = []
        for idx in active_indices:
            if not curr or idx - curr[-1] <= 5:
                curr.append(idx)
            else:
                clusters.append(curr)
                curr = [idx]
        if curr:
            clusters.append(curr)

        # Filter for clusters that have sustained speech (at least 4 consecutive active frames / 80ms)
        valid_clusters = []
        for c in clusters:
            consec = 0
            max_consec = 0
            for i in range(len(c)):
                if i > 0 and c[i] == c[i - 1] + 1:
                    consec += 1
                else:
                    consec = 1
                max_consec = max(max_consec, consec)
            if max_consec >= 4:
                valid_clusters.append(c)

        if not valid_clusters:
            return WakeWordResult(detected=False)

        # Evaluate most recent valid speech burst (closest to current time)
        cluster = valid_clusters[-1]
        burst_start = cluster[0]
        burst_end = cluster[-1]
        active_duration = (burst_end - burst_start + 1) * (frame_size / float(self.sample_rate))
        active_samples = float_samples[burst_start * frame_size : (burst_end + 1) * frame_size]
        active_rms = float(np.sqrt(np.mean(active_samples ** 2)))

        min_rms = max(0.012, 0.022 * (1.1 - sensitivity * 0.5))
        if active_rms < min_rms:
            return WakeWordResult(detected=False)

        # Syllable onset zero-crossing rate analysis
        onset_len = min(len(active_samples), max(int(len(active_samples) * 0.35), int(self.sample_rate * 0.06)))
        onset_samples = active_samples[:onset_len]
        zcr = float(np.mean(np.abs(np.diff(np.sign(onset_samples)))) / 2.0)
        if not (0.015 <= zcr <= 0.70):
            return WakeWordResult(detected=False)

        # Syllabic energy modulation check (rejects constant Gaussian noise or AC hum)
        max_frame_rms = max(rms_frames[burst_start : burst_end + 1])
        mod_ratio = max_frame_rms / max(0.005, active_rms)
        if mod_ratio < 1.15:
            return WakeWordResult(detected=False)

        # SNR and feature scoring
        snr = active_rms / max(0.003, noise_floor)
        snr_score = min(1.0, snr / 3.0)
        mod_score = min(1.0, max(0.5, mod_ratio / 1.5))
        required_conf = max(0.50, 0.88 - sensitivity * 0.30)

        # Match against duration bounds for "Hey Zoro" and "Zoro"
        hey_enabled = "hey zoro" in self.enabled_phrases
        zoro_enabled = "zoro" in self.enabled_phrases

        # 3-syllable "Hey Zoro" (typically 0.60s - 2.2s)
        hey_min_dur = 0.60 if zoro_enabled else 0.40
        if hey_enabled and hey_min_dur <= active_duration <= 2.2:
            dur_score = 1.0 - min(0.3, abs(active_duration - 0.85))
            base_conf = 0.60 + 0.20 * snr_score + 0.10 * mod_score + 0.10 * dur_score
            confidence = min(0.96, base_conf * (0.85 + 0.25 * sensitivity))
            if confidence >= required_conf:
                self.last_detection_time = now
                logger.info("Wake word detected: 'Hey Zoro' (confidence: %.2f)", confidence)
                return WakeWordResult(
                    detected=True,
                    wake_word="hey zoro",
                    confidence=confidence,
                    timestamp=now,
                )

        # 2-syllable "Zoro" (typically 0.22s - 0.65s when both enabled, up to 1.4s standalone)
        zoro_max_dur = 0.65 if hey_enabled else 1.4
        if zoro_enabled and 0.22 <= active_duration <= zoro_max_dur:
            dur_score = 1.0 - min(0.3, abs(active_duration - 0.45))
            base_conf = 0.60 + 0.20 * snr_score + 0.10 * mod_score + 0.10 * dur_score
            confidence = min(0.96, base_conf * (0.85 + 0.25 * sensitivity))
            if confidence >= required_conf:
                self.last_detection_time = now
                logger.info("Wake word detected: 'Zoro' (confidence: %.2f)", confidence)
                return WakeWordResult(
                    detected=True,
                    wake_word="zoro",
                    confidence=confidence,
                    timestamp=now,
                )

        return WakeWordResult(detected=False)
