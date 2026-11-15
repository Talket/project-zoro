"""Central Orchestrator Core Engine coordinating subsystems, IPC, and telemetry."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from zoro.benchmarks.runner import HardwareAwareBenchmarkRunner
from zoro.config.settings import ZoroSettings, get_settings
from zoro.core.event_bus import AsyncEventBus
from zoro.core.governor import ResourceGovernor
from zoro.core.health import HealthMonitor
from zoro.core.lifecycle import LifecycleManager, LifecycleState
from zoro.ipc.pipe_server import NamedPipeServer
from zoro.models.base import BaseModelProvider
from zoro.models.llama_cpp import LlamaCppProvider
from zoro.models.mock import MockModelProvider
from zoro.models.ollama import OllamaProvider
from zoro.models.registry import ProviderRegistry
from zoro.orchestrator.orchestrator import ZoroOrchestrator
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.tools.builtin.file_tools import (
    FileDeleteTool,
    FileDiscoveryTool,
    FileMoveTool,
    FileReadMetadataTool,
    ReportGeneratorTool,
)
from zoro.tools.registry import ToolRegistry

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

        # ---------------------------------------------------------
        # Intelligence Core Subsystems (Milestone 02)
        # ---------------------------------------------------------
        # 1. Tool Registry & Builtin tools
        self.tool_registry = ToolRegistry(
            db=self.db,
            audit=self.audit,
            permission_gate=self.permissions,
        )
        self._register_default_tools()

        # 2. AI Provider Registry & Adapters
        self.provider_registry = ProviderRegistry()
        self._mock_provider = MockModelProvider()
        self._ollama_provider = OllamaProvider()
        self._llama_provider = LlamaCppProvider()

        self.provider_registry.register_provider("mock", self._mock_provider, default_model="mock-v1")
        self.provider_registry.register_provider("ollama", self._ollama_provider, default_model="qwen2.5:3b")
        self.provider_registry.register_provider("llama.cpp", self._llama_provider, default_model="default")
        self.provider_registry.set_active_provider("mock")

        # Backward compatibility alias
        self.model_provider: BaseModelProvider = self._mock_provider

        # 3. Model Benchmark Runner
        self.benchmark_runner = HardwareAwareBenchmarkRunner(
            registry=self.provider_registry,
            db=self.db,
        )

        # 4. Central Orchestrator
        self.orchestrator = ZoroOrchestrator(
            provider_registry=self.provider_registry,
            tool_registry=self.tool_registry,
            db=self.db,
            audit=self.audit,
            event_bus=self.event_bus,
            emergency_mgr=self.emergency_mgr,
        )

        self._telemetry_task: Optional[asyncio.Task] = None
        self._is_initialized = False

    def _register_default_tools(self) -> None:
        """Register default safe system tools."""
        self.tool_registry.register(FileDiscoveryTool(self.permissions))
        self.tool_registry.register(FileReadMetadataTool(self.permissions))
        self.tool_registry.register(ReportGeneratorTool(self.permissions))
        self.tool_registry.register(FileMoveTool(self.permissions))
        self.tool_registry.register(FileDeleteTool(self.permissions))

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

        # 6. Subscribe internal event bus to broadcast notifications
        await self.event_bus.subscribe("orchestrator.state_changed", self._on_orchestrator_state_changed)
        await self.event_bus.subscribe("plan.approval_required", self._on_approval_required)
        await self.event_bus.subscribe("step.started", self._on_step_event)
        await self.event_bus.subscribe("step.completed", self._on_step_event)

        # 7. Register IPC JSON-RPC handlers
        self._register_ipc_handlers()

        # 8. Start Named Pipe Server
        self.ipc_server.start(loop=asyncio.get_running_loop())

        # 9. Start telemetry background broadcasting
        self._telemetry_task = asyncio.create_task(self._telemetry_loop(), name="zoro-telemetry-loop")

        self.lifecycle.transition_to(LifecycleState.RUNNING)
        self._is_initialized = True
        logger.info("ZORO Core Engine & Intelligence Core initialized successfully.")
        return True

    def _register_ipc_handlers(self) -> None:
        """Register JSON-RPC methods exposed to the Desktop UI."""
        # Foundation RPCs
        self.ipc_server.register_handler("system.echo", self._rpc_echo)
        self.ipc_server.register_handler("system.get_health", self._rpc_get_health)
        self.ipc_server.register_handler("system.get_state", self._rpc_get_state)
        self.ipc_server.register_handler("system.shutdown", self._rpc_shutdown)
        self.ipc_server.register_handler("system.query_audit", self._rpc_query_audit)

        # Intelligence Core RPCs (Milestone 02)
        self.ipc_server.register_handler("ai.get_providers", self._rpc_ai_get_providers)
        self.ipc_server.register_handler("ai.select_provider", self._rpc_ai_select_provider)
        self.ipc_server.register_handler("ai.list_models", self._rpc_ai_list_models)
        self.ipc_server.register_handler("ai.run_benchmark", self._rpc_ai_run_benchmark)
        self.ipc_server.register_handler("ai.get_benchmarks", self._rpc_ai_get_benchmarks)
        self.ipc_server.register_handler("ai.prompt", self._rpc_ai_prompt)
        self.ipc_server.register_handler("ai.get_status", self._rpc_ai_get_status)
        self.ipc_server.register_handler("ai.resolve_approval", self._rpc_ai_resolve_approval)
        self.ipc_server.register_handler("ai.approve", self._rpc_ai_resolve_approval)
        self.ipc_server.register_handler("ai.cancel", self._rpc_ai_cancel)
        self.ipc_server.register_handler("ai.list_tools", self._rpc_ai_list_tools)

    # ---------------------------------------------------------
    # Foundation RPC Implementations
    # ---------------------------------------------------------
    async def _rpc_echo(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"echo": params.get("message", "ack")}

    async def _rpc_get_health(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.health.sample_metrics()

    async def _rpc_get_state(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "state": self.lifecycle.state.value,
            "lifecycle_state": self.lifecycle.state.value,
            "orchestrator_state": self.orchestrator.state.value,
            "instance_id": self.settings.instance_id,
            "pid": os.getpid(),
        }

    async def _rpc_shutdown(self, params: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("Shutdown requested via Named Pipe IPC.")
        self.lifecycle.request_shutdown()
        return {"status": "shutdown_initiated"}

    async def _rpc_query_audit(self, params: Dict[str, Any]) -> Dict[str, Any]:
        limit = params.get("limit", 20)
        records = await self.audit.get_recent_records(limit=limit)
        return {"records": records}

    # ---------------------------------------------------------
    # Intelligence Core RPC Implementations (Milestone 02)
    # ---------------------------------------------------------
    async def _rpc_ai_get_providers(self, params: Dict[str, Any]) -> Dict[str, Any]:
        health_map = await self.provider_registry.get_all_provider_health()
        return {
            "active_provider": self.provider_registry.active_provider_name,
            "active_model": self.provider_registry.get_active_model(),
            "providers": {k: v.model_dump() for k, v in health_map.items()},
        }

    async def _rpc_ai_select_provider(self, params: Dict[str, Any]) -> Dict[str, Any]:
        provider_name = params.get("provider")
        model_name = params.get("model")
        if not provider_name:
            raise ValueError("Parameter 'provider' is required.")
        self.provider_registry.set_active_provider(provider_name, model_name=model_name)
        self.model_provider = self.provider_registry.get_provider(provider_name)
        return {
            "status": "success",
            "active_provider": self.provider_registry.active_provider_name,
            "active_model": self.provider_registry.get_active_model(),
        }

    async def _rpc_ai_list_models(self, params: Dict[str, Any]) -> Dict[str, Any]:
        catalog = await self.provider_registry.discover_all_models()
        return {
            "catalog": {k: [m.model_dump() for m in v] for k, v in catalog.items()}
        }

    async def _rpc_ai_run_benchmark(self, params: Dict[str, Any]) -> Dict[str, Any]:
        provider = params.get("provider", self.provider_registry.active_provider_name)
        model = params.get("model", self.provider_registry.get_active_model())
        result = await self.benchmark_runner.run_benchmark(provider, model)
        return {"result": result.model_dump()}

    async def _rpc_ai_get_benchmarks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        limit = params.get("limit", 10)
        rows = await self.db.execute_read(
            """
            SELECT model_name, provider_id, timestamp, ttft_ms, tokens_per_sec,
                   ram_used_mb, vram_used_mb, gpu_temp_c, structured_json_score,
                   instruction_following_score, tool_calling_supported
            FROM model_benchmarks ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        )
        benchmarks = []
        for r in rows:
            benchmarks.append({
                "model_name": r[0],
                "provider_id": r[1],
                "timestamp": r[2],
                "ttft_ms": r[3],
                "tokens_per_sec": r[4],
                "ram_used_mb": r[5],
                "vram_used_mb": r[6],
                "gpu_temp_c": r[7],
                "structured_json_score": r[8],
                "instruction_following_score": r[9],
                "tool_calling_supported": bool(r[10]),
            })
        return {"benchmarks": benchmarks}

    async def _rpc_ai_prompt(self, params: Dict[str, Any]) -> Dict[str, Any]:
        prompt = params.get("prompt") or params.get("message") or ""
        conversation_id = params.get("conversation_id")
        if not prompt:
            raise ValueError("Parameter 'prompt' cannot be empty.")
        response = await self.orchestrator.process_user_request(prompt, conversation_id=conversation_id)
        return response.model_dump()

    async def _rpc_ai_get_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        plan_dump = self.orchestrator._active_plan.model_dump() if self.orchestrator._active_plan else None
        return {
            "orchestrator_state": self.orchestrator.state.value,
            "active_plan": plan_dump,
        }

    async def _rpc_ai_resolve_approval(self, params: Dict[str, Any]) -> Dict[str, Any]:
        token = params.get("token")
        approved = params.get("approved", True)
        if not token:
            raise ValueError("Parameter 'token' is required.")
        response = await self.orchestrator.resolve_approval(token, approved=approved)
        return response.model_dump()

    async def _rpc_ai_cancel(self, params: Dict[str, Any]) -> Dict[str, Any]:
        self.orchestrator.cancel()
        return {"status": "cancelled"}

    async def _rpc_ai_list_tools(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"tools": self.tool_registry.list_tools()}

    # ---------------------------------------------------------
    # Event Bus Handlers for Real-Time UI Broadcasting
    # ---------------------------------------------------------
    async def _on_orchestrator_state_changed(self, topic: str, payload: Dict[str, Any]) -> None:
        self.ipc_server.broadcast_notification("ai.state_changed", payload)

    async def _on_approval_required(self, topic: str, payload: Dict[str, Any]) -> None:
        self.ipc_server.broadcast_notification("ai.approval_requested", payload)

    async def _on_step_event(self, topic: str, payload: Dict[str, Any]) -> None:
        self.ipc_server.broadcast_notification("ai.step_update", payload)

    async def _telemetry_loop(self) -> None:
        """Periodic background loop sampling hardware and emitting telemetry."""
        logger.debug("Telemetry sampling background loop started.")
        while self.lifecycle.is_running:
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

        # Cancel active orchestrator operations
        self.orchestrator.cancel()

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
