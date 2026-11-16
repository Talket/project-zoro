"""Audio Device Discovery and Configuration for Windows Audio Endpoints."""

from __future__ import annotations

import logging
from typing import List, Optional
import sounddevice as sd

from zoro.voice.models import AudioDevice

logger = logging.getLogger(__name__)


class AudioDeviceManager:
    """Discovers, filters, and manages Windows audio input and output devices."""

    def __init__(self) -> None:
        self._cached_devices: Optional[List[dict]] = None

    def refresh(self) -> None:
        """Force device discovery refresh from PortAudio / sounddevice."""
        try:
            self._cached_devices = list(sd.query_devices())
        except Exception as e:
            logger.error("Failed to query sound devices: %s", e)
            self._cached_devices = []

    def get_all_devices(self) -> List[AudioDevice]:
        """Return all discovered sound devices."""
        try:
            raw_devices = sd.query_devices()
            default_in, default_out = sd.default.device
        except Exception as e:
            logger.warning("Error querying audio devices: %s. Returning fallback list.", e)
            return [
                AudioDevice(
                    index=0,
                    name="Default Mock Microphone",
                    channels=1,
                    sample_rate=16000.0,
                    is_input=True,
                    is_default=True,
                    api="Mock",
                ),
                AudioDevice(
                    index=1,
                    name="Default Mock Speakers",
                    channels=2,
                    sample_rate=44100.0,
                    is_input=False,
                    is_default=True,
                    api="Mock",
                ),
            ]

        devices: List[AudioDevice] = []
        host_apis = {}
        try:
            for api in sd.query_hostapis():
                host_apis[api["index"]] = api["name"]
        except Exception:
            pass

        for idx, dev in enumerate(raw_devices):
            api_name = host_apis.get(dev.get("hostapi"), "DirectSound")
            is_def_in = (idx == default_in)
            is_def_out = (idx == default_out)

            if dev["max_input_channels"] > 0:
                devices.append(
                    AudioDevice(
                        index=idx,
                        name=dev["name"],
                        channels=dev["max_input_channels"],
                        sample_rate=float(dev["default_samplerate"]),
                        is_input=True,
                        is_default=is_def_in,
                        api=api_name,
                    )
                )

            if dev["max_output_channels"] > 0:
                devices.append(
                    AudioDevice(
                        index=idx,
                        name=dev["name"],
                        channels=dev["max_output_channels"],
                        sample_rate=float(dev["default_samplerate"]),
                        is_input=False,
                        is_default=is_def_out,
                        api=api_name,
                    )
                )

        return devices

    def list_input_devices(self) -> List[AudioDevice]:
        """Return all available microphone and capture devices."""
        return [d for d in self.get_all_devices() if d.is_input]

    def list_output_devices(self) -> List[AudioDevice]:
        """Return all available speakers and playback devices."""
        return [d for d in self.get_all_devices() if not d.is_input]

    def get_default_input_device(self) -> Optional[AudioDevice]:
        """Return primary default microphone."""
        inputs = self.list_input_devices()
        for d in inputs:
            if d.is_default:
                return d
        return inputs[0] if inputs else None

    def get_default_output_device(self) -> Optional[AudioDevice]:
        """Return primary default speakers."""
        outputs = self.list_output_devices()
        for d in outputs:
            if d.is_default:
                return d
        return outputs[0] if outputs else None

    def find_device_by_name(self, name_contains: str, is_input: bool = True) -> Optional[AudioDevice]:
        """Fuzzy match device by substring name."""
        name_lower = name_contains.lower()
        devices = self.list_input_devices() if is_input else self.list_output_devices()
        for d in devices:
            if name_lower in d.name.lower():
                return d
        return None

    def get_device_by_index(self, index: int) -> Optional[AudioDevice]:
        """Return audio device matching PortAudio index."""
        for d in self.get_all_devices():
            if d.index == index:
                return d
        return None
