"""Unit and integration tests for Voice Activity Detection (WebRTC VAD and Energy Fallback)."""

import time
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from zoro.voice.models import VADConfig, VADResult
from zoro.voice.vad.detector import VoiceActivityDetector, WEBRTC_AVAILABLE


def test_vad_initialization():
    """Verify default VAD setup and config."""
    cfg = VADConfig(aggressiveness=2, silence_duration_threshold_sec=0.5, speech_onset_threshold_sec=0.05)
    det = VoiceActivityDetector(config=cfg, sample_rate=16000)
    assert det.config.aggressiveness == 2
    assert det.sample_rate == 16000
    assert not det._in_speech


def test_vad_silence_detection():
    """Verify processing pure silence frames produces no speech."""
    det = VoiceActivityDetector(sample_rate=16000)
    # 20ms at 16kHz = 320 samples = 640 bytes
    silence = np.zeros(320, dtype=np.int16).tobytes()

    for _ in range(10):
        res = det.process_frame(silence)
        assert isinstance(res, VADResult)
        assert res.is_speech is False
        assert res.energy < 0.001


def test_vad_speech_onset_and_ended():
    """Verify speech onset triggers when speech exceeds threshold, and speech_ended triggers after silence."""
    cfg = VADConfig(aggressiveness=1, speech_onset_threshold_sec=0.04, silence_duration_threshold_sec=0.04)
    det = VoiceActivityDetector(config=cfg, sample_rate=16000)

    # 440Hz tone simulating active speech (20ms frames)
    t = np.linspace(0, 0.02, 320, endpoint=False)
    loud_tone = (0.5 * 32767.0 * np.sin(2 * np.pi * 440 * t)).astype(np.int16).tobytes()
    silence = np.zeros(320, dtype=np.int16).tobytes()

    # Step 1: Send speech frames
    onset_detected = False
    for _ in range(5):
        res = det.process_frame(loud_tone)
        if res.speech_onset:
            onset_detected = True
        time.sleep(0.015)

    assert onset_detected is True
    assert det._in_speech is True

    # Step 2: Send silence frames to trigger termination
    time.sleep(0.05)
    ended_detected = False
    for _ in range(5):
        res = det.process_frame(silence)
        if res.speech_ended:
            ended_detected = True
        time.sleep(0.02)

    assert ended_detected is True
    assert det._in_speech is False


def test_vad_energy_fallback():
    """Verify energy fallback works when webrtcvad is disabled or unavailable."""
    cfg = VADConfig(energy_threshold=0.02, speech_onset_threshold_sec=0.02, silence_duration_threshold_sec=0.02)
    det = VoiceActivityDetector(config=cfg, sample_rate=16000)
    det.vad_engine = None  # Force energy-only mode

    # Empty frame
    res_empty = det.process_frame(b"")
    assert res_empty.is_speech is False

    # High energy frame
    loud_tone = (np.ones(320, dtype=np.int16) * 10000).tobytes()
    det.process_frame(loud_tone)
    time.sleep(0.03)
    res = det.process_frame(loud_tone)
    assert res.speech_onset is True
    assert det._in_speech is True

    # Reset
    det.reset()
    assert not det._in_speech
