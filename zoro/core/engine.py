"""Central Orchestrator Core Engine coordinating subsystems, IPC, and telemetry."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any, Dict, Optional

from zoro.config.settings import ZoroSettings, get_settings
from zoro.core.event_bus import AsyncEventBus
from zoro.core.governor import ResourceGovernor
from zoro.core.health import HealthMonitor
from zoro.core.lifecycle import LifecycleManager, LifecycleState
from zoro.ipc.pipe_server import NamedPipeServer
from zoro.models.base import BaseModelProvider
from zoro.models.mock import MockModelProvider
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager

logger = logging.getLogger(__name__)


class ZoroEngine:
    """The central artificial intelligence orchestrator and runtime coordinator."""

    def __init__(self, settings: Optional[ZoroSettings] = None) -> None:
        self.settings = settings or get_settings()
        self.emergency_mgr = EmergencyManager(
            halt_lock_path=self.settings.halt_lock_path,
            pid_path=self.settings.pid_path,
        )
        self.lifecycle = LifecycleManager(self.emergency_mgr)
        self.event_bus = AsyncEventBus()
        self.db = DatabaseManager(settings=self.settings)
        self.audit = AuditLogger(self.db, settings=self.settings)
        self.permissions = PermissionGate(strict_mode=self.settings.strict_permissions)
        self.health = HealthMonitor(settings=self.settings)
        self.governor = ResourceGovernor(self.health, settings=self.settings)
        self.ipc_server = NamedPipeServer(pipe_name=self.settings.pipe_name, settings=self.settings)
        self.model_provider: BaseModelProvider = MockModelProvider()

        self._telemetry_task: Optional[asyncio.Task] = None
        self._is_initialized = False

    async def initialize(self) -> bool:
        """Run pre-flight checks and initialize all engine subsystems."""
        if self._is_initialized:
            return True

        self.lifecycle.transition_to(LifecycleState.INITIALIZING)

        # 1. Preflight safety check
        if not self.lifecycle.preflight_check():
            logger.critical("Engine initialization blocked by emergency halt state!")
            return False

        # 2. Record PID
        self.emergency_mgr.record_pid(os.getpid())

        # 3. Initialize database & migrations
        await self.db.initialize()

        # 4. Initialize hardware & health telemetry
        self.health.initialize()

        # 5. Log audit event
        await self.audit.log_event(
            actor="System",
            action="ENGINE_STARTUP",
            resource="ZoroEngine",
            details={"instance_id": self.settings.instance_id, "pid": os.getpid()},
        )

        # 6. Register IPC JSON-RPC handlers
        self._register_ipc_handlers()

        # 7. Start Named Pipe Server
        self.ipc_server.start(loop=asyncio.get_running_loop())

        # 8. Start telemetry background broadcasting
        self._telemetry_task = asyncio.create_task(self._telemetry_loop(), name="zoro-telemetry-loop")

        self.lifecycle.transition_to(LifecycleState.RUNNING)
        self._is_initialized = True
        logger.info("ZORO Core Engine initialized successfully.")
        return True

    def _register_ipc_handlers(self) -> None:
        """Register JSON-RPC methods exposed to the Desktop UI."""
        self.ipc_server.register_handler("system.echo", self._rpc_echo)
        self.ipc_server.register_handler("system.get_health", self._rpc_get_health)
        self.ipc_server.register_handler("system.get_state", self._rpc_get_state)
        self.ipc_server.register_handler("system.shutdown", self._rpc_shutdown)
        self.ipc_server.register_handler("system.query_audit", self._rpc_query_audit)

    async def _rpc_echo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"echo": params.get("message", "ack")}

    async def _rpc_get_health(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.health.sample_metrics()

    async def _rpc_get_state(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"state": self.lifecycle.state.value, "instance_id": self.settings.instance_id}

    async def _rpc_shutdown(self, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Shutdown requested via IPC command.")
        self.lifecycle.request_shutdown()
        return {"status": "shutdown_initiated"}

    async def _rpc_query_audit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        limit = min(int(params.get("limit", 20)), 100)
        rows = await self.db.execute_read(
            "SELECT id, timestamp, actor, action, resource, details_json, prev_hash, record_hash "
            "FROM audit_records ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        records = [
            {
                "id": r[0],
                "timestamp": r[1],
                "actor": r[2],
                "action": r[3],
                "resource": r[4],
                "details": r[5],
                "prev_hash": r[6],
                "record_hash": r[7],
            }
            for r in rows
        ]
        return {"records": records}

    async def _telemetry_loop(self) -> None:
        """Periodic background task broadcasting live health metrics to the UI."""
        while self.lifecycle.state == LifecycleState.RUNNING:
            try:
                metrics = self.health.sample_metrics()
                # Check idle model eviction
                self.governor.check_idle_eviction()
                # Broadcast over Named Pipe
                self.ipc_server.broadcast_notification("telemetry.update", metrics)
                # Publish on internal event bus
                await self.event_bus.publish("system.health.telemetry", metrics)
            except Exception as e:
                logger.error("Error in telemetry loop: %s", e)

            await asyncio.sleep(self.settings.telemetry_interval_sec)

    async def run(self) -> None:
        """Run engine event loop until shutdown is signaled."""
        initialized = await self.initialize()
        if not initialized:
            logger.critical("Engine initialization failed. Exiting.")
            return

        self.lifecycle.setup_signal_handlers()
        logger.info("Engine running. Awaiting shutdown signal...")
        await self.lifecycle.wait_for_shutdown()
        await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully stop all subsystems."""
        logger.info("Shutting down ZORO Core Engine...")
        self.lifecycle.transition_to(LifecycleState.SHUTTING_DOWN)

        # Cancel telemetry task
        if self._telemetry_task:
            self._telemetry_task.cancel()
            try:
                await self._telemetry_task
            except asyncio.CancelledError:
                pass
            self._telemetry_task = None

        # Stop IPC server
        self.ipc_server.stop()

        # Log shutdown in audit log
        try:
            await self.audit.log_event(
                actor="System",
                action="ENGINE_SHUTDOWN",
                resource="ZoroEngine",
                details={"instance_id": self.settings.instance_id},
            )
        except Exception:
            pass

        # Close database
        await self.db.close()

        # Shutdown health & NVML
        self.health.close()

        # Clear recorded PID
        self.emergency_mgr.clear_pid()

        self.lifecycle.transition_to(LifecycleState.STOPPED)
        logger.info("ZORO Core Engine stopped cleanly.")
