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
        self._on_started_callbacks: list[Callable[[], None]] = []
        self._on_finished_callbacks: list[Callable[[], None]] = []
        self._lock = threading.Lock()

    @property
    def is_playing(self) -> bool:
        """Indicates whether speaker audio is currently playing."""
        return self._is_playing

    def register_on_started(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when physical audio playback begins."""
        with self._lock:
            if callback not in self._on_started_callbacks:
                self._on_started_callbacks.append(callback)

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

    def _notify_started(self) -> None:
        with self._lock:
            callbacks = list(self._on_started_callbacks)
        for cb in callbacks:
            try:
                cb()
            except Exception as e:
                logger.error("Error in playback started callback: %s", e)

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
        """Worker thread executing audio playback chunks with device-native resampling & stereo support."""
        logger.debug("Playback worker started at %d Hz.", sample_rate)
        stream = None
        target_device = self._current_device_index if self._current_device_index is not None else sd.default.device[1]
        target_sr = sample_rate
        target_channels = 1

        try:
            # Query physical output device properties
            try:
                dev_info = sd.query_devices(target_device)
                dev_sr = int(dev_info.get("default_samplerate", 0))
                if dev_sr > 0:
                    target_sr = dev_sr
                max_ch = int(dev_info.get("max_output_channels", 1))
                target_channels = 2 if max_ch >= 2 else 1
                logger.debug(
                    "Target speaker device %s: native %d Hz, %d channels",
                    target_device,
                    target_sr,
                    target_channels,
                )
            except Exception as e_dev:
                logger.debug("Could not inspect target output device (%s); using %d Hz mono", e_dev, sample_rate)

            # Attempt stream opening: primary device -> default device -> mono fallback
            try:
                stream = sd.OutputStream(
                    samplerate=target_sr,
                    channels=target_channels,
                    dtype="int16",
                    device=target_device,
                )
                stream.start()
            except Exception as e_primary:
                logger.warning(
                    "Primary output stream on device %s failed (%s). Attempting default stream.",
                    target_device,
                    e_primary,
                )
                try:
                    stream = sd.OutputStream(
                        samplerate=target_sr,
                        channels=target_channels,
                        dtype="int16",
                    )
                    stream.start()
                except Exception as e_secondary:
                    logger.warning("Default output stream failed (%s). Attempting raw mono.", e_secondary)
                    try:
                        target_sr = sample_rate
                        target_channels = 1
                        stream = sd.OutputStream(
                            samplerate=sample_rate,
                            channels=1,
                            dtype="int16",
                        )
                        stream.start()
                    except Exception as e_mono:
                        logger.warning(
                            "Could not open native output stream (%s). Simulating playback.", e_mono
                        )
                        stream = None

            # Notify listeners that physical playback is actively running
            self._notify_started()

            while not self._stop_event.is_set():
                try:
                    chunk = self._queue.get(timeout=0.35)
                except queue.Empty:
                    # Queue exhausted
                    break

                if chunk is None or self._stop_event.is_set():
                    self._queue.task_done()
                    break

                # Apply volume scaling
                samples = np.frombuffer(chunk, dtype=np.int16)
                if len(samples) == 0:
                    self._queue.task_done()
                    continue

                if self.volume < 0.99:
                    scaled = (samples.astype(np.float32) * self.volume).astype(np.int16)
                    samples = scaled

                # Resample int16 PCM if hardware device requires different sample rate
                if sample_rate != target_sr and len(samples) > 1:
                    old_len = len(samples)
                    new_len = int(old_len * target_sr / sample_rate)
                    if new_len > 0:
                        old_indices = np.linspace(0, old_len - 1, old_len)
                        new_indices = np.linspace(0, old_len - 1, new_len)
                        samples = np.interp(new_indices, old_indices, samples).astype(np.int16)

                # Duplicate mono to stereo if hardware device has 2+ channels
                if target_channels == 2:
                    chunk_to_write = np.column_stack((samples, samples))
                else:
                    chunk_to_write = samples

                if stream is not None:
                    try:
                        stream.write(chunk_to_write)
                    except Exception as e:
                        err_desc = e.args[0] if (hasattr(e, "args") and e.args) else type(e).__name__
                        logger.warning("Error writing audio chunk to speaker stream: %s", err_desc)
                else:
                    # Synthetic delay matching chunk duration
                    duration_sec = len(samples) / float(target_sr)
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
