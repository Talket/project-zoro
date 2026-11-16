"""Unit and integration tests for Local Offline Wake-Word Detection ('Zoro' and 'Hey Zoro')."""

import time
import numpy as np
import pytest

from zoro.voice.models import WakeWordConfig, WakeWordResult
from zoro.voice.wake.wake_word import WakeWordDetector


def test_wake_word_detector_init_and_defaults():
    """Verify default wake words are both enabled ('zoro' and 'hey zoro')."""
    det = WakeWordDetector()
    assert det.is_phrase_enabled("zoro") is True
    assert det.is_phrase_enabled("hey zoro") is True
    assert det.is_phrase_enabled("alexa") is False


def test_wake_word_independent_toggling():
    """Verify independent enable/disable of wake phrases."""
    det = WakeWordDetector()

    det.disable_phrase("zoro")
    assert det.is_phrase_enabled("zoro") is False
    assert det.is_phrase_enabled("hey zoro") is True

    det.disable_phrase("hey zoro")
    assert det.is_phrase_enabled("hey zoro") is False

    det.enable_phrase("zoro")
    assert det.is_phrase_enabled("zoro") is True


def test_wake_word_push_to_talk():
    """Verify Push-to-Talk activation."""
    det = WakeWordDetector()
    res = det.trigger_push_to_talk()
    assert res.detected is True
    assert res.wake_word == "push_to_talk"
    assert res.confidence == 1.0


def test_wake_word_text_hint_detection():
    """Verify wake word triggers correctly via text hint for 'Zoro' and 'Hey Zoro'."""
    det = WakeWordDetector(config=WakeWordConfig(cooldown_seconds=0.01))

    # 1. Test "Hey Zoro"
    res1 = det.process_audio(b"", text_hint="hey zoro can you hear me")
    assert res1.detected is True
    assert res1.wake_word == "hey zoro"
    assert res1.confidence >= 0.9

    time.sleep(0.02)

    # 2. Test "Zoro"
    res2 = det.process_audio(b"", text_hint="zoro what is the weather")
    assert res2.detected is True
    assert res2.wake_word == "zoro"

    time.sleep(0.02)

    # 3. Test disabled phrase is ignored
    det.disable_phrase("hey zoro")
    res3 = det.process_audio(b"", text_hint="hey zoro")
    # Should fall back to "zoro" if "zoro" is in text and enabled
    assert res3.wake_word == "zoro"

    det.disable_phrase("zoro")
    res4 = det.process_audio(b"", text_hint="zoro hey zoro")
    assert res4.detected is False


def test_wake_word_self_voice_suppression():
    """Verify wake-word detection is suppressed when the assistant is speaking."""
    is_speaking = True
    det = WakeWordDetector(
        config=WakeWordConfig(cooldown_seconds=0.01),
        is_assistant_speaking_callback=lambda: is_speaking,
    )

    # While speaking, wake word must be rejected even with exact match
    res = det.process_audio(b"", text_hint="hey zoro")
    assert res.detected is False

    # Once playback stops, detection immediately resumes
    is_speaking = False
    res2 = det.process_audio(b"", text_hint="hey zoro")
    assert res2.detected is True
    assert res2.wake_word == "hey zoro"


def test_wake_word_cooldown_enforcement():
    """Verify cooldown period prevents back-to-back duplicate triggers."""
    det = WakeWordDetector(config=WakeWordConfig(cooldown_seconds=1.0))

    res1 = det.process_audio(b"", text_hint="zoro")
    assert res1.detected is True

    # Immediate second call within cooldown must be suppressed
    res2 = det.process_audio(b"", text_hint="zoro")
    assert res2.detected is False


def test_wake_word_acoustic_processing():
    """Verify acoustic feature analysis on synthetic audio."""
    det = WakeWordDetector(config=WakeWordConfig(sensitivity=0.5, cooldown_seconds=0.01), sample_rate=16000)

    # Silence
    silence = np.zeros(8000, dtype=np.int16).tobytes()
    res_silence = det.process_audio(silence)
    assert res_silence.detected is False

    # Audio too short (<400ms)
    short_audio = np.ones(3200, dtype=np.int16).tobytes()  # 200ms
    res_short = det.process_audio(short_audio)
    assert res_short.detected is False

    # 0.8s synthetic audio with high zero-crossing rate and sufficient energy
    np.random.seed(42)
    noise = np.random.uniform(-0.3, 0.3, 12800)  # 0.8s at 16kHz
    audio_bytes = (noise * 32767.0).astype(np.int16).tobytes()

    res_acoustic = det.process_audio(audio_bytes)
    # Checks that acoustic branch runs without error
    assert isinstance(res_acoustic, WakeWordResult)
