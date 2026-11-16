"""Voice Subsystem Health and Device Connection Watchdog."""

from __future__ import annotations

import logging
from typing import Any, Dict

from zoro.voice.audio.devices import AudioDeviceManager

logger = logging.getLogger(__name__)


class VoiceHealthMonitor:
    """Monitors device connections and voice subsystem operational health."""

    def __init__(self, device_manager: AudioDeviceManager) -> None:
        self.device_manager = device_manager

    def check_health(self) -> Dict[str, Any]:
        """Verify device availability and subsystem integrity."""
        in_devices = self.device_manager.list_input_devices()
        out_devices = self.device_manager.list_output_devices()

        has_mic = len(in_devices) > 0
        has_speaker = len(out_devices) > 0
        is_healthy = has_mic and has_speaker

        return {
            "healthy": is_healthy,
            "microphone_available": has_mic,
            "speaker_available": has_speaker,
            "input_devices_count": len(in_devices),
            "output_devices_count": len(out_devices),
            "default_input": self.device_manager.get_default_input_device().name if has_mic else None,
            "default_output": self.device_manager.get_default_output_device().name if has_speaker else None,
        }
