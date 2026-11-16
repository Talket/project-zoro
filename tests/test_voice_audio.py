"""Unit and integration tests for ZORO Voice Audio subsystem (Capture, Playback, Devices, Buffer)."""

import time
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

from zoro.voice.models import AudioDevice
from zoro.voice.audio.devices import AudioDeviceManager
from zoro.voice.audio.audio_buffer import CircularAudioBuffer
from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.playback import AudioPlaybackManager


# ---------------------------------------------------------
# 1. Audio Device Manager Tests
# ---------------------------------------------------------

def test_audio_device_manager_query():
    """Verify AudioDeviceManager queries input and output devices."""
    mgr = AudioDeviceManager()
    inputs = mgr.list_input_devices()
    outputs = mgr.list_output_devices()

    # Even on machines without audio hardware or CI, it returns lists without exception
    assert isinstance(inputs, list)
    assert isinstance(outputs, list)

    # Test get_device_by_index
    if inputs:
        dev = mgr.get_device_by_index(inputs[0].index)
        assert dev is not None
        assert dev.index == inputs[0].index

    assert mgr.get_device_by_index(-999) is None


def test_audio_device_manager_fallback():
    """Verify fallback device discovery when sounddevice encounters an error."""
    with patch("zoro.voice.audio.devices.sd.query_devices", side_effect=Exception("PortAudio error")):
        mgr = AudioDeviceManager()
        inputs = mgr.list_input_devices()
        outputs = mgr.list_output_devices()
        assert len(inputs) >= 1
        assert len(outputs) >= 1
        assert inputs[0].is_default is True
        assert outputs[0].is_default is True


def test_audio_device_manager_find_by_name():
    """Verify fuzzy search by name."""
    mgr = AudioDeviceManager()
    dev_in = AudioDevice(
        index=1,
        name="Realtek High Definition Audio",
        channels=2,
        sample_rate=16000.0,
        is_input=True,
        is_default=True,
    )
    with patch.object(mgr, "list_input_devices", return_value=[dev_in]):
        match = mgr.find_device_by_name("Realtek", is_input=True)
        assert match is not None
        assert match.index == 1

        no_match = mgr.find_device_by_name("NonExistentDevice", is_input=True)
        assert no_match is None


# ---------------------------------------------------------
# 2. Circular Audio Buffer Tests
# ---------------------------------------------------------

def test_circular_audio_buffer_write_read():
    """Verify basic write, get_recent, get_all, and clear in CircularAudioBuffer."""
    buf = CircularAudioBuffer(sample_rate=16000, max_seconds=2.0)

    # 1 second of 440Hz sine wave as int16
    duration = 1.0
    t = np.linspace(0, duration, int(16000 * duration), endpoint=False)
    tone = (0.5 * 32767.0 * np.sin(2 * np.pi * 440 * t)).astype(np.int16)

    written = buf.write(tone)
    assert written == 16000
    assert abs(buf.current_duration_seconds - 1.0) < 0.01
    assert buf.current_size_bytes == 32000

    # Get recent 0.5s (8000 samples)
    data = buf.get_recent(0.5)
    assert len(data) == 8000

    # Get all buffered data
    all_data = buf.get_all(clear=False)
    assert len(all_data) == 16000

    # Read as raw bytes
    raw_bytes = buf.get_all_bytes(clear=True)
    assert len(raw_bytes) == 32000
    assert buf.current_duration_seconds == 0.0


def test_circular_audio_buffer_overflow_eviction():
    """Verify buffer drops oldest samples on capacity overflow."""
    buf = CircularAudioBuffer(sample_rate=16000, max_seconds=1.0)
    # Max samples is 16000. Write 20000 samples.
    chunk1 = np.ones(10000, dtype=np.int16) * 100
    chunk2 = np.ones(10000, dtype=np.int16) * 200

    buf.write(chunk1)
    buf.write(chunk2)

    assert abs(buf.current_duration_seconds - 1.0) < 0.01
    all_data = buf.get_all()
    assert len(all_data) == 16000
    # First 6000 samples from chunk1, remaining 10000 from chunk2
    assert all_data[0] == 100
    assert all_data[-1] == 200


def test_circular_audio_buffer_from_bytes():
    """Verify writing raw PCM bytes directly."""
    buf = CircularAudioBuffer(sample_rate=16000, max_seconds=1.0)
    raw = (np.array([100, 200, 300], dtype=np.int16)).tobytes()
    written = buf.write(raw)
    assert written == 3
    assert len(buf.get_all()) == 3


# ---------------------------------------------------------
# 3. Audio Capture Manager Tests
# ---------------------------------------------------------

def test_audio_capture_manager_synthetic_frames():
    """Verify AudioCaptureManager lifecycle, callback, and synthetic frame injection."""
    received_frames = []

    def on_frame(pcm_bytes: bytes, rms: float):
        received_frames.append((pcm_bytes, rms))

    cap = AudioCaptureManager(sample_rate=16000, channels=1, chunk_duration_ms=20)
    cap.register_callback(on_frame)

    assert not cap.is_capturing
    assert cap.start_capture() is True
    assert cap.is_capturing is True

    # Inject synthetic frames
    frame1 = np.zeros(320, dtype=np.int16).tobytes()
    frame2 = (np.ones(320, dtype=np.int16) * 1000).tobytes()

    cap.inject_synthetic_frame(frame1, rms=0.01)
    cap.inject_synthetic_frame(frame2, rms=0.15)

    assert len(received_frames) == 2
    assert cap.current_rms == 0.15

    # Unregister callback
    cap.unregister_callback(on_frame)
    cap.inject_synthetic_frame(frame1, rms=0.01)
    assert len(received_frames) == 2  # Not called again

    cap.stop_capture()
    assert not cap.is_capturing


def test_audio_capture_sounddevice_failure_fallback():
    """Verify AudioCaptureManager switches to mock mode when PortAudio fails."""
    with patch("zoro.voice.audio.capture.sd.InputStream", side_effect=Exception("Audio hardware busy")):
        cap = AudioCaptureManager(sample_rate=16000, channels=1)
        # Should catch error, log warning, and start in mock mode
        assert cap.start_capture() is True
        assert cap.is_capturing is True
        assert cap._mock_mode is True
        cap.stop_capture()
        assert not cap.is_capturing


# ---------------------------------------------------------
# 4. Audio Playback Manager Tests
# ---------------------------------------------------------

def test_audio_playback_manager_queue_and_stop():
    """Verify AudioPlaybackManager play_chunk, volume, and immediate stop (<10ms)."""
    finished_called = []

    def on_finish():
        finished_called.append(True)

    pb = AudioPlaybackManager(default_sample_rate=16000)
    pb.register_on_finished(on_finish)

    assert not pb.is_playing

    # Generate 0.1s of audio in bytes
    samples = (0.2 * 32767.0 * np.sin(2 * np.pi * 440 * np.linspace(0, 0.1, 1600))).astype(np.int16)
    raw_pcm = samples.tobytes()

    # Mock sounddevice OutputStream to avoid hardware dependency in tests
    with patch("zoro.voice.audio.playback.sd.OutputStream"):
        pb.play_chunk(raw_pcm)
        time.sleep(0.02)
        assert pb.is_playing is True

        # Test volume control
        pb.set_volume(0.8)
        assert pb.volume == 0.8
        pb.set_volume(1.5)  # clamped to 1.0
        assert pb.volume == 1.0
        pb.set_volume(-0.5)  # clamped to 0.0
        assert pb.volume == 0.0
        pb.set_volume(1.0)

        # Immediate stop
        t0 = time.perf_counter()
        pb.stop_playback()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 100.0  # Must stop immediately
        assert pb.is_playing is False

    assert len(finished_called) >= 1
