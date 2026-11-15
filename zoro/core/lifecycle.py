"""Lifecycle State Machine and Windows Power Management Coordinator."""

from __future__ import annotations

import asyncio
from enum import Enum
import logging
import signal
from typing import Callable, List, Optional

from zoro.security.emergency import EmergencyManager

logger = logging.getLogger(__name__)


class LifecycleState(str, Enum):
    """Lifecycle states of the ZORO Core Runtime."""
    UNINITIALIZED = "UNINITIALIZED"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"         # Sleep state
    SHUTTING_DOWN = "SHUTTING_DOWN"
    STOPPED = "STOPPED"
    EMERGENCY_HALTED = "EMERGENCY_HALTED"


class LifecycleManager:
    """Coordinates lifecycle transitions, signal handlers, and power events."""

    def __init__(self, emergency_mgr: Optional[EmergencyManager] = None) -> None:
        self.emergency_mgr = emergency_mgr or EmergencyManager()
        self.state: LifecycleState = LifecycleState.UNINITIALIZED
        self._shutdown_event = asyncio.Event()
        self._shutdown_hooks: List[Callable[[], None]] = []

    def preflight_check(self) -> bool:
        """
        Verify that ZORO is permitted to start.
        Returns False if an emergency halt lock exists.
        """
        is_halted, data = self.emergency_mgr.is_halted()
        if is_halted:
            self.state = LifecycleState.EMERGENCY_HALTED
            logger.critical("Preflight Check FAILED: Emergency halt lock active! %s", data)
            return False
        return True

    def transition_to(self, new_state: LifecycleState) -> None:
        """Transition lifecycle state with logging."""
        old_state = self.state
        self.state = new_state
        logger.info("Lifecycle transition: %s -> %s", old_state.value, new_state.value)

    def register_shutdown_hook(self, hook: Callable[[], None]) -> None:
        """Register synchronous or asynchronous cleanup callback."""
        self._shutdown_hooks.append(hook)

    def setup_signal_handlers(self) -> None:
        """Register SIGINT and SIGTERM handlers for graceful exit."""
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_shutdown)
            except (NotImplementedError, AttributeError):
                # Windows event loop fallback
                signal.signal(sig, lambda s, f: self.request_shutdown())

    def request_shutdown(self) -> None:
        """Request graceful shutdown."""
        if self.state in (LifecycleState.SHUTTING_DOWN, LifecycleState.STOPPED):
            return
        logger.info("Shutdown requested. Initiating graceful stop...")
        self.transition_to(LifecycleState.SHUTTING_DOWN)
        self._shutdown_event.set()

    async def wait_for_shutdown(self) -> None:
        """Block until shutdown is signaled."""
        await self._shutdown_event.wait()

    def on_suspend(self) -> None:
        """Invoked when Windows enters sleep."""
        if self.state == LifecycleState.RUNNING:
            self.transition_to(LifecycleState.SUSPENDED)
            logger.info("System entering sleep. Pausing runtime tasks...")

    def on_resume(self) -> None:
        """Invoked when Windows resumes from sleep."""
        if self.state == LifecycleState.SUSPENDED:
            # Re-check halt lock
            if not self.preflight_check():
                return
            self.transition_to(LifecycleState.RUNNING)
            logger.info("System resumed from sleep. Runtime re-activated.")
