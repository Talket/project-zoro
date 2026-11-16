"""Audio Playback and Streaming Speaker Output Engine."""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Optional
import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class AudioPlaybackManager:
    """Manages audio playback through speaker devices with immediate cancellation support."""

    def __init__(self, default_sample_rate: int = 22050) -> None:
        self.default_sample_rate = default_sample_rate
        self.volume = 1.0  # 0.0 to 1.0
        self._current_device_index: Optional[int] = None

        self._queue: queue.Queue[Optional[bytes]] = queue.Queue()
        self._is_playing = False
        self._stop_event = threading.Event()
        self._playback_thread: Optional[threading.Thread] = None
        self._on_finished_callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    @property
    def is_playing(self) -> bool:
        """Indicates whether speaker audio is currently playing."""
        return self._is_playing

    def register_on_finished(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when playback finishes or is cancelled."""
        with self._lock:
            if callback not in self._on_finished_callbacks:
                self._on_finished_callbacks.append(callback)

    def set_volume(self, volume: float) -> None:
        """Set output volume level between 0.0 and 1.0."""
        self.volume = max(0.0, min(1.0, volume))

    def play_chunk(self, pcm_bytes: bytes, sample_rate: Optional[int] = None) -> None:
        """Enqueue a PCM audio chunk for sequential playback."""
        if not pcm_bytes:
            return

        self._stop_event.clear()
        self._queue.put(pcm_bytes)

        if not self._is_playing:
            self._start_worker(sample_rate or self.default_sample_rate)

    def play_complete_audio(self, pcm_bytes: bytes, sample_rate: Optional[int] = None) -> None:
        """Stop current playback, enqueue audio, and start immediate playback."""
        self.stop_playback()
        self.play_chunk(pcm_bytes, sample_rate)

    def stop_playback(self) -> None:
        """Immediately stop all audio playback, clear pending chunks, and notify listeners."""
        self._stop_event.set()
        try:
            sd.stop()
        except Exception:
            pass

        # Clear remaining queue items
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                self._queue.task_done()
            except queue.Empty:
                break

        self._is_playing = False
        self._notify_finished()
        logger.debug("Audio playback stopped immediately.")

    def stop(self) -> None:
        """Alias for stop_playback to provide uniform interface across audio managers."""
        self.stop_playback()

    def _notify_finished(self) -> None:
        with self._lock:
            callbacks = list(self._on_finished_callbacks)
        for cb in callbacks:
            try:
                cb()
            except Exception as e:
                logger.error("Error in playback finished callback: %s", e)

    def _start_worker(self, sample_rate: int) -> None:
        self._is_playing = True
        self._playback_thread = threading.Thread(
            target=self._worker_loop, args=(sample_rate,), daemon=True, name="AudioPlaybackWorker"
        )
        self._playback_thread.start()

    def _worker_loop(self, sample_rate: int) -> None:
        """Worker thread executing audio playback chunks."""
        logger.debug("Playback worker started at %d Hz.", sample_rate)
        try:
            stream = None
            try:
                stream = sd.OutputStream(
                    samplerate=sample_rate,
                    channels=1,
                    dtype="int16",
                    device=self._current_device_index,
                )
                stream.start()
            except Exception as e_stream:
                logger.warning("Could not open native output stream (%s). Simulating playback.", e_stream)
                stream = None

            while not self._stop_event.is_set():
                try:
                    chunk = self._queue.get(timeout=0.1)
                except queue.Empty:
                    # Queue exhausted
                    break

                if chunk is None or self._stop_event.is_set():
                    self._queue.task_done()
                    break

                # Apply volume scaling
                samples = np.frombuffer(chunk, dtype=np.int16)
                if self.volume < 0.99:
                    scaled = (samples.astype(np.float32) * self.volume).astype(np.int16)
                    chunk_to_play = scaled.tobytes()
                else:
                    chunk_to_play = chunk

                if stream is not None:
                    try:
                        stream.write(np.frombuffer(chunk_to_play, dtype=np.int16))
                    except Exception as e:
                        logger.error("Error writing audio chunk to speaker stream: %s", e)
                else:
                    # Synthetic delay matching chunk duration
                    duration_sec = len(samples) / float(sample_rate)
                    time.sleep(min(0.05, duration_sec))

                self._queue.task_done()

        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

            self._is_playing = False
            self._notify_finished()
            logger.debug("Playback worker terminated.")
