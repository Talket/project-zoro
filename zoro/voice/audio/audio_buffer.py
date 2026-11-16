"""Thread-Safe Circular Audio Ring Buffer for Real-Time Streaming Audio."""

from __future__ import annotations

import logging
import threading
from typing import Optional, Union
import numpy as np

logger = logging.getLogger(__name__)


class CircularAudioBuffer:
    """Thread-safe circular ring buffer with bounded capacity and overflow eviction."""

    def __init__(self, sample_rate: int = 16000, max_seconds: float = 30.0) -> None:
        self.sample_rate = sample_rate
        self.max_seconds = max_seconds
        self.max_samples = int(sample_rate * max_seconds)
        self._buffer = np.zeros(self.max_samples, dtype=np.int16)
        self._write_pos = 0
        self._total_samples_written = 0
        self._lock = threading.Lock()

    def write(self, data: Union[bytes, np.ndarray]) -> int:
        """Write incoming audio samples to the ring buffer.

        Accepts raw int16 PCM bytes or a NumPy 1D array.
        """
        if isinstance(data, bytes):
            samples = np.frombuffer(data, dtype=np.int16)
        else:
            samples = data.astype(np.int16)

        num_samples = len(samples)
        if num_samples == 0:
            return 0

        with self._lock:
            if num_samples >= self.max_samples:
                # Audio larger than buffer capacity; retain only the most recent part
                samples = samples[-self.max_samples :]
                num_samples = len(samples)
                self._buffer[:] = samples
                self._write_pos = 0
                self._total_samples_written += num_samples
                return num_samples

            end_pos = self._write_pos + num_samples
            if end_pos <= self.max_samples:
                self._buffer[self._write_pos : end_pos] = samples
            else:
                first_part = self.max_samples - self._write_pos
                self._buffer[self._write_pos :] = samples[:first_part]
                self._buffer[: num_samples - first_part] = samples[first_part:]

            self._write_pos = end_pos % self.max_samples
            self._total_samples_written += num_samples

        return num_samples

    def get_recent(self, seconds: float) -> np.ndarray:
        """Retrieve the most recent N seconds of audio as an int16 NumPy array."""
        num_samples = min(int(self.sample_rate * seconds), self.max_samples)
        with self._lock:
            available = min(self._total_samples_written, self.max_samples)
            if available == 0:
                return np.zeros(0, dtype=np.int16)

            samples_to_read = min(num_samples, available)
            start_pos = (self._write_pos - samples_to_read) % self.max_samples

            if start_pos + samples_to_read <= self.max_samples:
                return self._buffer[start_pos : start_pos + samples_to_read].copy()
            else:
                first_part = self.max_samples - start_pos
                part1 = self._buffer[start_pos:]
                part2 = self._buffer[: samples_to_read - first_part]
                return np.concatenate((part1, part2))

    def get_all(self, clear: bool = False) -> np.ndarray:
        """Retrieve all currently buffered audio."""
        with self._lock:
            available = min(self._total_samples_written, self.max_samples)
            if available == 0:
                return np.zeros(0, dtype=np.int16)

            start_pos = (self._write_pos - available) % self.max_samples
            if start_pos + available <= self.max_samples:
                data = self._buffer[start_pos : start_pos + available].copy()
            else:
                first_part = self.max_samples - start_pos
                part1 = self._buffer[start_pos:]
                part2 = self._buffer[: available - first_part]
                data = np.concatenate((part1, part2))

            if clear:
                self.clear_unlocked()

            return data

    def get_all_bytes(self, clear: bool = False) -> bytes:
        """Retrieve all currently buffered audio as raw int16 PCM bytes."""
        return self.get_all(clear=clear).tobytes()

    def clear(self) -> None:
        """Reset the buffer immediately."""
        with self._lock:
            self.clear_unlocked()

    def clear_unlocked(self) -> None:
        self._buffer.fill(0)
        self._write_pos = 0
        self._total_samples_written = 0

    @property
    def current_duration_seconds(self) -> float:
        """Return the duration of active audio in the buffer."""
        with self._lock:
            available = min(self._total_samples_written, self.max_samples)
            return available / self.sample_rate

    @property
    def current_size_bytes(self) -> int:
        """Return the size in bytes of buffered audio."""
        with self._lock:
            available = min(self._total_samples_written, self.max_samples)
            return available * 2  # 2 bytes per int16
