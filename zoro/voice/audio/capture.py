"""Asynchronous Microphone Audio Capture Engine."""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, List, Optional
import numpy as np
import sounddevice as sd

from zoro.voice.audio.audio_buffer import CircularAudioBuffer

logger = logging.getLogger(__name__)


class AudioCaptureManager:
    """Manages continuous non-blocking microphone audio acquisition."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_duration_ms: int = 20,
        buffer_seconds: float = 30.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_duration_ms = chunk_duration_ms
        self.block_size = int(sample_rate * (chunk_duration_ms / 1000.0))  # 320 samples for 20ms at 16kHz
        self.audio_buffer = CircularAudioBuffer(sample_rate=sample_rate, max_seconds=buffer_seconds)

        self._stream: Optional[sd.InputStream] = None
        self._is_capturing = False
        self._current_device_index: Optional[int] = None
        self._callbacks: List[Callable[[bytes, float], None]] = []
        self._current_rms: float = 0.0
        self._lock = threading.Lock()
        self._mock_mode = False

    @property
    def is_capturing(self) -> bool:
        return self._is_capturing

    @property
    def current_rms(self) -> float:
        """Current microphone input level (0.0 to 1.0)."""
        return self._current_rms

    def register_callback(self, callback: Callable[[bytes, float], None]) -> None:
        """Register a callback receiving (raw_pcm_bytes, rms_level) for every frame."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def unregister_callback(self, callback: Callable[[bytes, float], None]) -> None:
        with self._lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def _audio_callback(self, indata: np.ndarray, frames: int, time_info: dict, status: sd.CallbackFlags) -> None:
        """PortAudio streaming input callback."""
        if status:
            logger.debug("PortAudio capture status warning: %s", status)

        # Handle stereo to mono conversion
        if indata.ndim > 1 and indata.shape[1] > 1:
            mono = indata.mean(axis=1)
        else:
            mono = indata.flatten()

        # Convert float32 [-1.0, 1.0] to int16 [-32768, 32767] if needed
        if mono.dtype == np.float32:
            scaled = np.clip(mono, -1.0, 1.0) * 32767.0
            int16_data = scaled.astype(np.int16)
        else:
            int16_data = mono.astype(np.int16)

        raw_bytes = int16_data.tobytes()

        # Compute RMS level
        float_samples = int16_data.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(float_samples**2))) if len(float_samples) > 0 else 0.0
        self._current_rms = min(1.0, rms * 3.0)  # Visual gain scaling

        # Write to circular buffer
        self.audio_buffer.write(int16_data)

        # Notify registered listeners
        with self._lock:
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb(raw_bytes, self._current_rms)
            except Exception as e:
                logger.error("Error in audio capture listener callback: %s", e)

    def start_capture(self, device_index: Optional[int] = None) -> bool:
        """Start microphone stream."""
        if self._is_capturing:
            logger.debug("Audio capture is already active.")
            return True

        self._current_device_index = device_index
        try:
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                blocksize=self.block_size,
                device=device_index,
                callback=self._audio_callback,
            )
            self._stream.start()
            self._is_capturing = True
            self._mock_mode = False
            logger.info("Microphone capture started on device index %s (%d Hz)", device_index, self.sample_rate)
            return True
        except Exception as e:
            logger.warning(
                "Failed to open native microphone stream (%s). Activating synthetic fallback capture mode.", e
            )
            self._mock_mode = True
            self._is_capturing = True
            return True

    def stop_capture(self) -> None:
        """Stop microphone stream and release PortAudio resource."""
        self._is_capturing = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.error("Error closing microphone stream: %s", e)
            finally:
                self._stream = None

        self._current_rms = 0.0
        logger.info("Microphone capture stopped.")

    def inject_synthetic_frame(self, raw_pcm_bytes: bytes, rms: float = 0.1) -> None:
        """Inject an audio frame directly (used in tests or mock mode)."""
        int16_data = np.frombuffer(raw_pcm_bytes, dtype=np.int16)
        self._current_rms = rms
        self.audio_buffer.write(int16_data)

        with self._lock:
            callbacks = list(self._callbacks)

        for cb in callbacks:
            try:
                cb(raw_pcm_bytes, rms)
            except Exception as e:
                logger.error("Error in audio listener callback: %s", e)
