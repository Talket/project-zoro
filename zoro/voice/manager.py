"""Central Voice Interaction Facade for PROJECT ZORO."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from zoro.core.event_bus import EventBus
from zoro.orchestrator.orchestrator import ZoroOrchestrator
from zoro.security.emergency import EmergencyManager
from zoro.storage.db import DatabaseManager
from zoro.voice.audio.capture import AudioCaptureManager
from zoro.voice.audio.devices import AudioDeviceManager
from zoro.voice.audio.playback import AudioPlaybackManager
from zoro.voice.conversation.interruption import InterruptionManager
from zoro.voice.conversation.session import VoiceSessionManager
from zoro.voice.conversation.turn_manager import VoiceTurnManager
from zoro.voice.events import (
    VOICE_ERROR,
    VOICE_INTERRUPTED,
    VOICE_SPEAKING_FINISHED,
    VOICE_SPEAKING_STARTED,
    VOICE_STATE_CHANGED,
    VOICE_TRANSCRIPTION,
    VOICE_WAKE_DETECTED,
)
from zoro.voice.models import VoiceState
from zoro.voice.monitoring.health import VoiceHealthMonitor
from zoro.voice.monitoring.metrics import VoiceMetricsCollector
from zoro.voice.pipeline.voice_pipeline import VoicePipeline
from zoro.voice.stt.registry import STTRegistry
from zoro.voice.tts.registry import TTSRegistry
from zoro.voice.vad.detector import VoiceActivityDetector
from zoro.voice.wake.wake_word import WakeWordDetector

logger = logging.getLogger(__name__)


class VoiceManager:
    """Unified Facade managing ZORO's high-speed local voice interaction subsystem."""

    def __init__(
        self,
        db: DatabaseManager,
        orchestrator: ZoroOrchestrator,
        event_bus: Optional[EventBus] = None,
        emergency_mgr: Optional[EmergencyManager] = None,
    ) -> None:
        self.db = db
        self.orchestrator = orchestrator
        self.event_bus = event_bus
        self.emergency = emergency_mgr

        # 1. Audio layer
        self.devices = AudioDeviceManager()
        self.capture = AudioCaptureManager()
        self.playback = AudioPlaybackManager()

        # 2. VAD & Wake-word
        self.vad = VoiceActivityDetector()
        self.wake = WakeWordDetector(
            is_assistant_speaking_callback=lambda: self.playback.is_playing
        )

        # 3. STT & TTS Registries
        self.stt = STTRegistry()
        self.tts = TTSRegistry()

        # 4. Conversation & Interruption
        self.session_mgr = VoiceSessionManager(db=db)
        self.turn_mgr = VoiceTurnManager(
            orchestrator=orchestrator,
            tts_registry=self.tts,
            playback_manager=self.playback,
            session_manager=self.session_mgr,
        )
        self.interruption = InterruptionManager(playback_manager=self.playback)

        # 5. Monitoring
        self.metrics = VoiceMetricsCollector(db=db)
        self.health = VoiceHealthMonitor(device_manager=self.devices)

        # 6. Unified Streaming Pipeline
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.pipeline = VoicePipeline(
            capture=self.capture,
            playback=self.playback,
            vad=self.vad,
            wake=self.wake,
            stt=self.stt,
            turn_manager=self.turn_mgr,
            interruption=self.interruption,
            on_state_change=self._on_pipeline_state_change,
            on_transcription=self._on_transcription,
        )

    def _check_emergency_halt(self) -> bool:
        """Verify if system emergency halt is active."""
        if self.emergency:
            res = self.emergency.is_halted()
            is_halted = res[0] if isinstance(res, (tuple, list)) else bool(res)
            if is_halted:
                logger.warning("Emergency halt is active! Voice operations frozen.")
                self.disable()
                return True
        return False

    def _on_pipeline_state_change(self, state: VoiceState) -> None:
        """Emit state changes to EventBus in a thread-safe manner."""
        if self.event_bus:
            payload = {"state": state.value}
            target_loop = self._loop
            if target_loop and target_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.event_bus.publish(VOICE_STATE_CHANGED, payload),
                    target_loop,
                )
            else:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.event_bus.publish(VOICE_STATE_CHANGED, payload))
                except RuntimeError:
                    pass

    def _on_transcription(self, text: str, speaker: str) -> None:
        """Emit transcription events to EventBus for HUD display in a thread-safe manner."""
        if self.event_bus:
            payload = {"text": text, "speaker": speaker}
            target_loop = self._loop
            if target_loop and target_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.event_bus.publish("voice.transcription", payload),
                    target_loop,
                )
            else:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self.event_bus.publish("voice.transcription", payload))
                except RuntimeError:
                    pass

    async def initialize(self) -> None:
        """Initialize voice subsystem components."""
        if self._check_emergency_halt():
            return

        try:
            self._loop = asyncio.get_running_loop()
            self.pipeline.set_loop(self._loop)
        except RuntimeError:
            pass

        self.devices.refresh()
        await self.session_mgr.start_session(
            input_device=self.devices.get_default_input_device().name if self.devices.get_default_input_device() else None,
            output_device=self.devices.get_default_output_device().name if self.devices.get_default_output_device() else None,
            stt_provider=self.stt.active_provider_name,
            tts_provider=self.tts.active_provider_name,
        )
        logger.info("VoiceManager initialized.")

    async def shutdown(self) -> None:
        """Clean shutdown of voice pipeline and resources."""
        self.disable()
        await self.session_mgr.end_session(status="COMPLETED")
        logger.info("VoiceManager shut down.")

    def enable(self) -> bool:
        """Enable voice interaction."""
        if self._check_emergency_halt():
            return False
        self.pipeline.enable()
        return True

    def disable(self) -> bool:
        """Disable voice interaction."""
        self.pipeline.disable()
        return True

    def start_listening(self) -> bool:
        """Start listening for speech / wake word."""
        if self._check_emergency_halt():
            return False
        self.pipeline.set_listening(True)
        return True

    def stop_listening(self) -> bool:
        """Pause listening."""
        self.pipeline.set_listening(False)
        return True

    def trigger_push_to_talk(self) -> bool:
        """Activate Push-to-Talk."""
        if self._check_emergency_halt():
            return False
        self.pipeline.trigger_push_to_talk()
        return True

    def stop_speaking(self) -> bool:
        """Immediately halt active speech playback."""
        self.playback.stop_playback()
        return True

    def set_wake_word_phrase(self, phrase: str, enabled: bool) -> bool:
        """Enable or disable 'Zoro' or 'Hey Zoro' independently."""
        if enabled:
            self.wake.enable_phrase(phrase)
        else:
            self.wake.disable_phrase(phrase)
        return True

    async def set_stt_provider(self, name: str) -> bool:
        """Switch active speech-to-text provider."""
        return await self.stt.set_active_provider(name)

    async def set_tts_provider(self, name: str) -> bool:
        """Switch active text-to-speech provider."""
        return await self.tts.set_active_provider(name)

    def set_input_device(self, index: int) -> bool:
        """Set microphone input device by index."""
        self.capture.stop_capture()
        ok = self.capture.start_capture(device_index=index)
        return ok

    def set_output_device(self, index: int) -> bool:
        """Set speaker output device by index."""
        self.playback._current_device_index = index
        return True

    def get_status(self) -> Dict[str, Any]:
        """Return real-time voice subsystem state and metrics."""
        return {
            "state": self.pipeline.state.value,
            "is_enabled": self.pipeline.is_enabled,
            "is_listening": self.pipeline.is_listening,
            "is_playing": self.playback.is_playing,
            "rms_level": round(self.capture.current_rms, 3),
            "stt_provider": self.stt.active_provider_name,
            "tts_provider": self.tts.active_provider_name,
            "enabled_wake_phrases": list(self.wake.enabled_phrases),
            "conversation_id": self.turn_mgr.active_conversation_id,
            "health": self.health.check_health(),
        }

    def get_devices(self) -> Dict[str, Any]:
        """Return discovered input and output devices."""
        return {
            "input_devices": [d.model_dump() for d in self.devices.list_input_devices()],
            "output_devices": [d.model_dump() for d in self.devices.list_output_devices()],
            "default_input": self.devices.get_default_input_device().model_dump() if self.devices.get_default_input_device() else None,
            "default_output": self.devices.get_default_output_device().model_dump() if self.devices.get_default_output_device() else None,
        }

    async def clear_history(self) -> int:
        """Clear voice interaction history for privacy and reset dialogue session."""
        self.turn_mgr.reset_conversation()
        return await self.session_mgr.clear_history()
