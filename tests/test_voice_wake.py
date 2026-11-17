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


def test_wake_word_acoustic_speech_detection_both_phrases():
    """Verify acoustic detection for both 'zoro' and 'hey zoro' utterances."""
    det = WakeWordDetector(config=WakeWordConfig(sensitivity=0.7, cooldown_seconds=0.01), sample_rate=16000)
    fs = 16000

    # 1. Synthesize 'zoro' speech envelope (~0.40s)
    t_zoro = np.linspace(0, 0.40, int(fs * 0.40))
    env_zoro = np.abs(np.sin(2 * np.pi * 2.5 * t_zoro)) ** 0.8
    carrier_zoro = np.sin(2 * np.pi * 180 * t_zoro) + 0.5 * np.sin(2 * np.pi * 700 * t_zoro)
    carrier_zoro[:int(fs * 0.08)] += np.random.normal(0, 0.4, int(fs * 0.08))
    speech_zoro = (carrier_zoro * env_zoro * 0.15).astype(np.float32)

    buf_zoro = np.random.normal(0, 0.005, int(fs * 1.5)).astype(np.float32)
    buf_zoro[int(fs * 0.5) : int(fs * 0.5) + len(speech_zoro)] += speech_zoro
    pcm_zoro = (buf_zoro * 32767).clip(-32768, 32767).astype(np.int16).tobytes()

    res_zoro = det.process_audio(pcm_zoro)
    assert res_zoro.detected is True
    assert res_zoro.wake_word == "zoro"
    assert res_zoro.confidence >= 0.70

    # 2. Synthesize 'hey zoro' speech envelope (~0.85s)
    time.sleep(0.02)
    t_hey = np.linspace(0, 0.85, int(fs * 0.85))
    env_hey = np.abs(np.sin(2 * np.pi * 1.8 * t_hey)) ** 0.8
    carrier_hey = np.sin(2 * np.pi * 160 * t_hey) + 0.4 * np.sin(2 * np.pi * 650 * t_hey)
    carrier_hey[:int(fs * 0.1)] += np.random.normal(0, 0.3, int(fs * 0.1))
    speech_hey = (carrier_hey * env_hey * 0.15).astype(np.float32)

    buf_hey = np.random.normal(0, 0.005, int(fs * 1.5)).astype(np.float32)
    buf_hey[int(fs * 0.4) : int(fs * 0.4) + len(speech_hey)] += speech_hey
    pcm_hey = (buf_hey * 32767).clip(-32768, 32767).astype(np.int16).tobytes()

    res_hey = det.process_audio(pcm_hey)
    assert res_hey.detected is True
    assert res_hey.wake_word == "hey zoro"
    assert res_hey.confidence >= 0.70


def test_wake_word_noise_rejection():
    """Verify flat noise, constant hum, and low-energy audio are strictly rejected."""
    det = WakeWordDetector(config=WakeWordConfig(sensitivity=0.6, cooldown_seconds=0.01), sample_rate=16000)
    fs = 16000

    # Low-energy noise
    low_noise = np.random.normal(0, 0.005, int(fs * 1.0))
    res_low = det.process_audio((low_noise * 32767).astype(np.int16).tobytes())
    assert res_low.detected is False

    # Flat unmodulated white noise (mod_ratio < 1.15)
    flat_noise = np.random.normal(0, 0.05, int(fs * 0.8))
    res_flat = det.process_audio((flat_noise * 32767).astype(np.int16).tobytes())
    assert res_flat.detected is False

    # Pure low-frequency sine hum (ZCR < 0.015)
    t = np.linspace(0, 0.8, int(fs * 0.8))
    hum = (np.sin(2 * np.pi * 60 * t) * 0.1 * 32767).astype(np.int16).tobytes()
    res_hum = det.process_audio(hum)
    assert res_hum.detected is False
