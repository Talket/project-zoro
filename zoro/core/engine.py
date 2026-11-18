"""Central Orchestrator Core Engine coordinating subsystems, IPC, and telemetry."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
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
from zoro.computer.apps import ApplicationController, ApplicationLauncher, ApplicationRegistry
from zoro.computer.filesystem import PathSecurityValidator, SecureFilesystemAgent
from zoro.computer.filesystem.models import FileRiskTier
from zoro.computer.sandbox import ExecutionPolicyEngine, ExecutionProfile, ExecutionSandboxManager
from zoro.computer.sandbox.resource_limits import ResourceGovernor as ComputerResourceGovernor
from zoro.computer.shell import CommandPolicy, CommandRiskTier, ControlledCommandRunner, ProcessMonitor
from zoro.computer.ui import (
    CoordinateFallbackInteractor,
    KeyboardController,
    MouseController,
    UIElementInspector,
    UIElementInteractor,
    UIVerificationEngine,
    WindowManager,
)
from zoro.computer.vision import ScreenCaptureManager, ScreenRegion, VisionModelInterface, WindowsOCR
from zoro.tools.builtin.computer_tools import (
    AppCloseTool,
    AppLaunchTool,
    ElementActionTool,
    ElementInspectTool,
    ScreenCaptureTool,
    ScreenOCRTool,
    ShellExecuteTool,
    WindowFocusTool,
    WindowListTool,
)
from zoro.tools.builtin.file_tools import (
    FileDeleteTool,
    FileDiscoveryTool,
    FileMoveTool,
    FileReadMetadataTool,
    ReportGeneratorTool,
)
from zoro.tools.registry import ToolRegistry
from zoro.voice import VoiceManager

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

        # 2. AI Provider Registry & Adapters
        self.provider_registry = ProviderRegistry()
        self._mock_provider = MockModelProvider()
        self._ollama_provider = OllamaProvider(base_url=self.settings.ollama_url)
        self._llama_provider = LlamaCppProvider()

        self.provider_registry.register_provider("mock", self._mock_provider, default_model="mock-v1")
        self.provider_registry.register_provider("ollama", self._ollama_provider, default_model=self.settings.primary_model)
        self.provider_registry.register_provider("llama.cpp", self._llama_provider, default_model="default")

        # Activate configured provider from settings if available, with fallback to mock
        active_prov_name = self.settings.model_provider if self.settings.model_provider in self.provider_registry._providers else "mock"
        self.provider_registry.set_active_provider(active_prov_name)

        # Backward compatibility alias
        self.model_provider: BaseModelProvider = self.provider_registry.get_provider(active_prov_name)

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

        # ---------------------------------------------------------
        # Computer Control Subsystems (Milestone 03)
        # ---------------------------------------------------------
        self.window_mgr = WindowManager()
        self.element_inspector = UIElementInspector()
        self.element_interactor = UIElementInteractor(self.element_inspector)
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.coordinate_fallback = CoordinateFallbackInteractor(self.mouse)
        self.capture_mgr = ScreenCaptureManager()
        self.ocr_engine = WindowsOCR()
        self.vision_provider = VisionModelInterface(ocr_engine=self.ocr_engine)
        self.path_validator = PathSecurityValidator(
            allowed_roots=[Path.cwd(), self.settings.data_dir, self.settings.data_dir.parent]
        )
        self.filesystem_agent = SecureFilesystemAgent(self.path_validator)
        self.command_policy = CommandPolicy()
        self.command_runner = ControlledCommandRunner(self.command_policy)
        self.process_monitor = ProcessMonitor(supervisor_pid=None)
        self.app_registry = ApplicationRegistry()
        self.app_launcher = ApplicationLauncher(self.app_registry, self.window_mgr)
        self.app_controller = ApplicationController(self.window_mgr, self.process_monitor)
        self.execution_policy = ExecutionPolicyEngine()
        self.comp_governor = ComputerResourceGovernor()
        self.sandbox_manager = ExecutionSandboxManager(
            db=self.db,
            policy=self.execution_policy,
            governor=self.comp_governor,
        )
        self.ui_verification = UIVerificationEngine(self.window_mgr, self.element_inspector)
        self.voice_mgr = VoiceManager(
            db=self.db,
            orchestrator=self.orchestrator,
            event_bus=self.event_bus,
            emergency_mgr=self.emergency_mgr,
        )
        self._register_default_tools()

        self._telemetry_task: Optional[asyncio.Task] = None
        self._is_initialized = False

    def _register_default_tools(self) -> None:
        """Register default safe system tools."""
        # Built-in File Tools
        self.tool_registry.register(FileDiscoveryTool(self.permissions))
        self.tool_registry.register(FileReadMetadataTool(self.permissions))
        self.tool_registry.register(ReportGeneratorTool(self.permissions))
        self.tool_registry.register(FileMoveTool(self.permissions))
        self.tool_registry.register(FileDeleteTool(self.permissions))

        # Milestone 03 Computer Control Tools
        self.tool_registry.register(WindowListTool(self.window_mgr))
        self.tool_registry.register(WindowFocusTool(self.window_mgr))
        self.tool_registry.register(ScreenCaptureTool(self.capture_mgr))
        self.tool_registry.register(ScreenOCRTool(self.capture_mgr, self.ocr_engine))
        self.tool_registry.register(ElementInspectTool(self.element_inspector))
        self.tool_registry.register(ElementActionTool(self.element_interactor))
        self.tool_registry.register(ShellExecuteTool(self.command_runner))
        self.tool_registry.register(AppLaunchTool(self.app_launcher))
        self.tool_registry.register(AppCloseTool(self.app_controller))

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

        # 2b. Ensure local AI provider daemon is accessible
        await self._ensure_local_ai_service()

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
        await self.event_bus.subscribe("voice.state_changed", self._on_voice_event)
        await self.event_bus.subscribe("voice.transcription", self._on_voice_event)
        await self.event_bus.subscribe("voice.speaking_started", self._on_voice_event)
        await self.event_bus.subscribe("voice.speaking_finished", self._on_voice_event)
        await self.event_bus.subscribe("voice.interrupted", self._on_voice_event)

        # 6b. Initialize voice subsystem
        await self.voice_mgr.initialize()

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

    async def _ensure_local_ai_service(self) -> None:
        """Ensure configured local AI engine (e.g. Ollama) is running and reachable."""
        if self.settings.model_provider == "ollama":
            health = await self._ollama_provider.health_check()
            if not health.is_available:
                import shutil
                ollama_bin = shutil.which("ollama") or r"C:\Users\ACER\AppData\Local\Programs\Ollama\ollama.exe"
                if os.path.exists(ollama_bin):
                    logger.info("Auto-starting local Ollama daemon (%s serve)...", ollama_bin)
                    try:
                        import subprocess
                        subprocess.Popen(
                            [ollama_bin, "serve"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                        )
                        for _ in range(8):
                            await asyncio.sleep(0.5)
                            h = await self._ollama_provider.health_check()
                            if h.is_available:
                                logger.info("Local Ollama daemon is ready and responding.")
                                break
                    except Exception as e:
                        logger.warning("Could not auto-start Ollama daemon: %s", e)

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

        # Computer Control RPCs (Milestone 03)
        self.ipc_server.register_handler("computer.list_windows", self._rpc_computer_list_windows)
        self.ipc_server.register_handler("computer.focus_window", self._rpc_computer_focus_window)
        self.ipc_server.register_handler("computer.window_action", self._rpc_computer_window_action)
        self.ipc_server.register_handler("computer.inspect_elements", self._rpc_computer_inspect_elements)
        self.ipc_server.register_handler("computer.element_action", self._rpc_computer_element_action)
        self.ipc_server.register_handler("computer.mouse_action", self._rpc_computer_mouse_action)
        self.ipc_server.register_handler("computer.keyboard_action", self._rpc_computer_keyboard_action)
        self.ipc_server.register_handler("computer.capture_screen", self._rpc_computer_capture_screen)
        self.ipc_server.register_handler("computer.ocr_screen", self._rpc_computer_ocr_screen)
        self.ipc_server.register_handler("computer.list_directory", self._rpc_computer_list_directory)
        self.ipc_server.register_handler("computer.read_file", self._rpc_computer_read_file)
        self.ipc_server.register_handler("computer.write_file", self._rpc_computer_write_file)
        self.ipc_server.register_handler("computer.delete_file", self._rpc_computer_delete_file)
        self.ipc_server.register_handler("computer.shell_execute", self._rpc_computer_shell_execute)
        self.ipc_server.register_handler("computer.list_apps", self._rpc_computer_list_apps)
        self.ipc_server.register_handler("computer.launch_app", self._rpc_computer_launch_app)
        self.ipc_server.register_handler("computer.close_app", self._rpc_computer_close_app)
        self.ipc_server.register_handler("computer.get_profile", self._rpc_computer_get_profile)
        self.ipc_server.register_handler("computer.set_profile", self._rpc_computer_set_profile)
        self.ipc_server.register_handler("computer.get_resource_status", self._rpc_computer_get_resource_status)

        # Voice Interaction RPCs (Milestone 04)
        self.ipc_server.register_handler("voice.get_status", self._rpc_voice_get_status)
        self.ipc_server.register_handler("voice.enable", self._rpc_voice_enable)
        self.ipc_server.register_handler("voice.disable", self._rpc_voice_disable)
        self.ipc_server.register_handler("voice.start_listening", self._rpc_voice_start_listening)
        self.ipc_server.register_handler("voice.stop_listening", self._rpc_voice_stop_listening)
        self.ipc_server.register_handler("voice.start_push_to_talk", self._rpc_voice_start_push_to_talk)
        self.ipc_server.register_handler("voice.stop_push_to_talk", self._rpc_voice_stop_push_to_talk)
        self.ipc_server.register_handler("voice.get_devices", self._rpc_voice_get_devices)
        self.ipc_server.register_handler("voice.set_input_device", self._rpc_voice_set_input_device)
        self.ipc_server.register_handler("voice.set_output_device", self._rpc_voice_set_output_device)
        self.ipc_server.register_handler("voice.get_providers", self._rpc_voice_get_providers)
        self.ipc_server.register_handler("voice.set_stt_provider", self._rpc_voice_set_stt_provider)
        self.ipc_server.register_handler("voice.set_tts_provider", self._rpc_voice_set_tts_provider)
        self.ipc_server.register_handler("voice.set_wake_word", self._rpc_voice_set_wake_word)
        self.ipc_server.register_handler("voice.stop_speaking", self._rpc_voice_stop_speaking)
        self.ipc_server.register_handler("voice.get_metrics", self._rpc_voice_get_metrics)
        self.ipc_server.register_handler("voice.clear_history", self._rpc_voice_clear_history)

        # Convenient aliases
        self.ipc_server.register_handler("voice.start", self._rpc_voice_enable)
        self.ipc_server.register_handler("voice.stop", self._rpc_voice_disable)
        self.ipc_server.register_handler("voice.push_to_talk", self._rpc_voice_start_push_to_talk)
        self.ipc_server.register_handler("voice.configure_wake_phrase", self._rpc_voice_set_wake_word)
        self.ipc_server.register_handler("voice.set_wake_listening", self._rpc_voice_set_wake_listening_alias)

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
    # Computer Control RPC Implementations (Milestone 03)
    # ---------------------------------------------------------
    async def _rpc_computer_list_windows(self, params: Dict[str, Any]) -> Dict[str, Any]:
        visible_only = params.get("visible_only", True)
        wins = self.window_mgr.list_windows(visible_only=visible_only)
        return {
            "windows": [
                {
                    "handle": w.handle,
                    "title": w.title,
                    "class_name": w.class_name,
                    "pid": w.pid,
                    "is_visible": w.is_visible,
                    "is_hung": w.is_hung,
                    "rect": {
                        "left": w.rect.left,
                        "top": w.rect.top,
                        "width": w.rect.width,
                        "height": w.rect.height,
                    },
                }
                for w in wins
            ]
        }

    async def _rpc_computer_focus_window(self, params: Dict[str, Any]) -> Dict[str, Any]:
        hwnd = params.get("handle")
        title = params.get("title")
        if not hwnd and title:
            w = self.window_mgr.find_window(title=title)
            if w:
                hwnd = w.handle
        if not hwnd:
            return {"success": False, "error": "Window not found"}
        ok = self.window_mgr.focus_window(hwnd)
        return {"success": ok, "handle": hwnd}

    async def _rpc_computer_window_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        hwnd = params.get("handle")
        action = params.get("action", "").lower()
        if not hwnd:
            return {"success": False, "error": "Parameter 'handle' required"}
        if action == "minimize":
            ok = self.window_mgr.minimize_window(hwnd)
        elif action == "maximize":
            ok = self.window_mgr.maximize_window(hwnd)
        elif action == "restore":
            ok = self.window_mgr.restore_window(hwnd)
        elif action == "close":
            ok = self.window_mgr.close_window(hwnd)
        else:
            return {"success": False, "error": f"Unknown window action: {action}"}
        return {"success": ok, "action": action, "handle": hwnd}

    async def _rpc_computer_inspect_elements(self, params: Dict[str, Any]) -> Dict[str, Any]:
        hwnd = params.get("handle")
        max_depth = params.get("max_depth", 3)
        if not hwnd:
            return {"success": False, "error": "Parameter 'handle' required"}
        elems = self.element_inspector.list_elements(hwnd, max_depth=max_depth)
        return {
            "elements": [
                {
                    "name": e.name,
                    "control_type": e.control_type,
                    "automation_id": e.automation_id,
                    "is_enabled": e.is_enabled,
                    "rect": {
                        "left": e.bounding_rect.left,
                        "top": e.bounding_rect.top,
                        "width": e.bounding_rect.width,
                        "height": e.bounding_rect.height,
                    }
                    if e.bounding_rect
                    else None,
                }
                for e in elems
            ]
        }

    async def _rpc_computer_element_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        hwnd = params.get("handle")
        action = params.get("action", "").lower()
        criteria = params.get("criteria", {})
        text_val = params.get("text")
        if not hwnd:
            return {"success": False, "error": "Parameter 'handle' required"}

        allowed, req_app, reason = self.execution_policy.evaluate_ui_action(action)
        if not allowed:
            return {"success": False, "error": reason}

        if action == "invoke":
            res = self.element_interactor.invoke(hwnd, criteria)
        elif action == "set_value":
            res = self.element_interactor.set_value(hwnd, criteria, text_val or "")
        elif action == "toggle":
            res = self.element_interactor.toggle(hwnd, criteria)
        elif action == "select":
            res = self.element_interactor.select(hwnd, criteria)
        else:
            return {"success": False, "error": f"Unknown action: {action}"}

        await self.sandbox_manager.record_action(
            action_type=f"element.{action}",
            target=str(criteria),
            parameters=params,
            verified=res.success,
            error=res.error,
        )
        return {"success": res.success, "error": res.error}

    async def _rpc_computer_mouse_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        action = params.get("action", "click").lower()
        x = params.get("x")
        y = params.get("y")
        clicks = params.get("clicks", 1)
        wheel = params.get("wheel", 0)
        allowed, _, reason = self.execution_policy.evaluate_ui_action(f"mouse.{action}")
        if not allowed:
            return {"success": False, "error": reason}

        if x is not None and y is not None:
            self.mouse.move_to(int(x), int(y))
        if action == "click":
            self.mouse.click(x, y, clicks=clicks)
        elif action == "right_click":
            self.mouse.right_click(x, y)
        elif action == "double_click":
            self.mouse.double_click(x, y)
        elif action == "scroll":
            self.mouse.scroll(wheel)
        return {"success": True, "action": action}

    async def _rpc_computer_keyboard_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        text = params.get("text")
        keys = params.get("keys")
        allowed, _, reason = self.execution_policy.evaluate_ui_action("keyboard")
        if not allowed:
            return {"success": False, "error": reason}
        if text:
            self.keyboard.type_text(text)
        elif keys:
            self.keyboard.send_keys(keys)
        return {"success": True}

    async def _rpc_computer_capture_screen(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.comp_governor.check_screenshot_rate():
            return {"success": False, "error": "Screenshot rate limit exceeded"}

        mon_idx = params.get("monitor_idx", 1)
        hwnd = params.get("handle")
        if hwnd:
            cap = self.capture_mgr.capture_active_window(handle=hwnd)
        else:
            cap = self.capture_mgr.capture_full_desktop(monitor_idx=mon_idx)

        self.comp_governor.record_screenshot()
        await self.sandbox_manager.record_screenshot_metadata(
            file_path=cap.image_path,
            width=cap.width,
            height=cap.height,
            monitor_idx=cap.monitor_idx,
        )
        return {
            "success": True,
            "image_path": str(cap.image_path),
            "width": cap.width,
            "height": cap.height,
            "size_bytes": cap.file_size_bytes,
        }

    async def _rpc_computer_ocr_screen(self, params: Dict[str, Any]) -> Dict[str, Any]:
        img_path = params.get("image_path")
        if not img_path:
            cap = self.capture_mgr.capture_full_desktop()
            img_path = str(cap.image_path)
        res = self.ocr_engine.recognize(img_path)
        return {
            "success": res.success,
            "text": res.full_text,
            "words": [{"text": w.text, "x": w.x, "y": w.y, "w": w.width, "h": w.height} for w in res.words],
            "error": res.error,
        }

    async def _rpc_computer_list_directory(self, params: Dict[str, Any]) -> Dict[str, Any]:
        dir_path = params.get("directory", str(Path.cwd()))
        max_items = params.get("max_items", 1000)
        try:
            files = self.filesystem_agent.list_dir(dir_path, max_items=max_items)
            return {
                "success": True,
                "files": [
                    {
                        "name": f.name,
                        "path": str(f.path),
                        "size_bytes": f.size_bytes,
                        "is_dir": f.is_dir,
                        "is_symlink": f.is_symlink,
                        "is_reparse_point": f.is_reparse_point,
                        "modified_at": f.modified_at.isoformat(),
                    }
                    for f in files
                ],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _rpc_computer_read_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path")
        max_bytes = params.get("max_bytes")
        if not path:
            return {"success": False, "error": "Parameter 'path' required"}
        try:
            content = self.filesystem_agent.read_file(path, max_bytes=max_bytes)
            return {"success": True, "content": content}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _rpc_computer_write_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path")
        content = params.get("content", "")
        overwrite = params.get("overwrite", True)
        if not path:
            return {"success": False, "error": "Parameter 'path' required"}

        risk = FileRiskTier.SENSITIVE if Path(path).exists() else FileRiskTier.LOW_RISK
        allowed, req_app, reason = self.execution_policy.evaluate_filesystem_action("write", risk)
        if not allowed:
            return {"success": False, "error": reason}

        res = self.filesystem_agent.write_file(path, content, overwrite=overwrite)
        await self.sandbox_manager.record_action(
            action_type="file.write",
            target=path,
            parameters={"overwrite": overwrite, "size": len(content)},
            risk_tier=risk.value,
            verified=res.success,
            error=res.error,
        )
        return {"success": res.success, "error": res.error}

    async def _rpc_computer_delete_file(self, params: Dict[str, Any]) -> Dict[str, Any]:
        path = params.get("path")
        recycle = params.get("to_recycle_bin", True)
        if not path:
            return {"success": False, "error": "Parameter 'path' required"}

        allowed, req_app, reason = self.execution_policy.evaluate_filesystem_action("delete", FileRiskTier.DESTRUCTIVE)
        if not allowed:
            return {"success": False, "error": reason}

        res = self.filesystem_agent.delete_file(path, to_recycle_bin=recycle)
        await self.sandbox_manager.record_action(
            action_type="file.delete",
            target=path,
            parameters={"recycle_bin": recycle},
            risk_tier="DESTRUCTIVE",
            verified=res.success,
            error=res.error,
        )
        return {"success": res.success, "recycle_bin": res.recycle_bin, "error": res.error}

    async def _rpc_computer_shell_execute(self, params: Dict[str, Any]) -> Dict[str, Any]:
        command = params.get("command")
        timeout = params.get("timeout_seconds")
        if not command:
            return {"success": False, "error": "Parameter 'command' required"}

        tier, reason, _ = self.command_policy.evaluate_command(command)
        allowed, req_app, pol_reason = self.execution_policy.evaluate_shell_execution(tier)
        if not allowed:
            return {"success": False, "error": pol_reason or reason}

        res = self.command_runner.execute(command, timeout=timeout)
        await self.sandbox_manager.record_shell_execution(
            command=res.command,
            args=res.args,
            returncode=res.returncode,
            stdout=res.stdout,
            stderr=res.stderr,
            duration=res.duration_seconds,
            risk_tier=res.risk_tier.value,
        )
        return {
            "success": res.returncode == 0,
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "duration_seconds": res.duration_seconds,
            "risk_tier": res.risk_tier.value,
            "timed_out": res.timed_out,
            "error": res.error,
        }

    async def _rpc_computer_list_apps(self, params: Dict[str, Any]) -> Dict[str, Any]:
        force = params.get("refresh", False)
        apps = self.app_registry.scan_installed_applications(force_refresh=force)
        return {
            "apps": [
                {
                    "name": a.name,
                    "display_name": a.display_name,
                    "executable_path": str(a.executable_path) if a.executable_path else None,
                    "publisher": a.publisher,
                    "version": a.version,
                }
                for a in apps
            ]
        }

    async def _rpc_computer_launch_app(self, params: Dict[str, Any]) -> Dict[str, Any]:
        app_name = params.get("app_name")
        if not app_name:
            return {"success": False, "error": "Parameter 'app_name' required"}
        ok, pid, hwnd = self.app_launcher.launch(app_name)
        return {"success": ok, "pid": pid, "handle": hwnd}

    async def _rpc_computer_close_app(self, params: Dict[str, Any]) -> Dict[str, Any]:
        app_target = params.get("target")
        force = params.get("force", False)
        if not app_target:
            return {"success": False, "error": "Parameter 'target' required"}
        ok = self.app_controller.close(app_target, force=force)
        return {"success": ok, "target": app_target}

    async def _rpc_computer_get_profile(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"profile": self.execution_policy.profile.value}

    async def _rpc_computer_set_profile(self, params: Dict[str, Any]) -> Dict[str, Any]:
        prof_str = params.get("profile", "")
        try:
            prof = ExecutionProfile(prof_str)
            self.execution_policy.set_profile(prof)
            return {"success": True, "profile": prof.value}
        except ValueError:
            return {"success": False, "error": f"Invalid profile: {prof_str}"}

    async def _rpc_computer_get_resource_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        ok, msg = self.comp_governor.check_system_health()
        return {
            "healthy": ok,
            "status_message": msg,
            "active_tasks": self.comp_governor.active_tasks_count,
        }

    # ---------------------------------------------------------
    # Voice Interaction RPC Implementations (Milestone 04)
    # ---------------------------------------------------------
    async def _rpc_voice_get_status(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.voice_mgr.get_status()

    async def _rpc_voice_enable(self, params: Dict[str, Any]) -> Dict[str, Any]:
        ok = self.voice_mgr.enable()
        return {"success": ok, "started": ok, "status": self.voice_mgr.get_status()}

    async def _rpc_voice_disable(self, params: Dict[str, Any]) -> Dict[str, Any]:
        ok = self.voice_mgr.disable()
        return {"success": ok, "started": not ok, "status": self.voice_mgr.get_status()}

    async def _rpc_voice_start_listening(self, params: Dict[str, Any]) -> Dict[str, Any]:
        ok = self.voice_mgr.start_listening()
        return {"success": ok, "is_listening": self.voice_mgr.pipeline.is_listening}

    async def _rpc_voice_stop_listening(self, params: Dict[str, Any]) -> Dict[str, Any]:
        ok = self.voice_mgr.stop_listening()
        return {"success": ok, "is_listening": self.voice_mgr.pipeline.is_listening}

    async def _rpc_voice_start_push_to_talk(self, params: Dict[str, Any]) -> Dict[str, Any]:
        ok = self.voice_mgr.trigger_push_to_talk()
        return {"success": ok, "state": self.voice_mgr.pipeline.state.value}

    async def _rpc_voice_stop_push_to_talk(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {"success": True}

    async def _rpc_voice_get_devices(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return self.voice_mgr.get_devices()

    async def _rpc_voice_set_input_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        index = params.get("device_index")
        if index is None:
            return {"success": False, "error": "Parameter 'device_index' required"}
        ok = self.voice_mgr.set_input_device(int(index))
        return {"success": ok, "device_index": index}

    async def _rpc_voice_set_output_device(self, params: Dict[str, Any]) -> Dict[str, Any]:
        index = params.get("device_index")
        if index is None:
            return {"success": False, "error": "Parameter 'device_index' required"}
        ok = self.voice_mgr.set_output_device(int(index))
        return {"success": ok, "device_index": index}

    async def _rpc_voice_get_providers(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "stt_providers": self.voice_mgr.stt.list_providers(),
            "active_stt": self.voice_mgr.stt.active_provider_name,
            "tts_providers": self.voice_mgr.tts.list_providers(),
            "active_tts": self.voice_mgr.tts.active_provider_name,
            "tts_voices": await self.voice_mgr.tts.list_voices(),
        }

    async def _rpc_voice_set_stt_provider(self, params: Dict[str, Any]) -> Dict[str, Any]:
        provider = params.get("provider")
        if not provider:
            return {"success": False, "error": "Parameter 'provider' required"}
        ok = await self.voice_mgr.set_stt_provider(provider)
        return {"success": ok, "active_stt": self.voice_mgr.stt.active_provider_name}

    async def _rpc_voice_set_tts_provider(self, params: Dict[str, Any]) -> Dict[str, Any]:
        provider = params.get("provider")
        if not provider:
            return {"success": False, "error": "Parameter 'provider' required"}
        ok = await self.voice_mgr.set_tts_provider(provider)
        return {"success": ok, "active_tts": self.voice_mgr.tts.active_provider_name}

    async def _rpc_voice_set_wake_word(self, params: Dict[str, Any]) -> Dict[str, Any]:
        phrase = params.get("phrase")
        enabled = params.get("enabled", True)
        if not phrase:
            return {"success": False, "error": "Parameter 'phrase' required"}
        ok = self.voice_mgr.set_wake_word_phrase(phrase, enabled)
        return {"success": ok, "enabled_wake_phrases": list(self.voice_mgr.wake.enabled_phrases)}

    async def _rpc_voice_stop_speaking(self, params: Dict[str, Any]) -> Dict[str, Any]:
        ok = self.voice_mgr.stop_speaking()
        return {"success": ok}

    async def _rpc_voice_get_metrics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        summary = self.voice_mgr.metrics.get_summary()
        current = self.voice_mgr.pipeline.metrics.model_dump()
        return {"summary": summary, "current": current}

    async def _rpc_voice_clear_history(self, params: Dict[str, Any]) -> Dict[str, Any]:
        count = await self.voice_mgr.clear_history()
        return {"success": True, "cleared": count}

    async def _rpc_voice_set_wake_listening_alias(self, params: Dict[str, Any]) -> Dict[str, Any]:
        enabled = params.get("enabled", True)
        if enabled:
            return await self._rpc_voice_start_listening(params)
        else:
            return await self._rpc_voice_stop_listening(params)

    # ---------------------------------------------------------
    # Event Bus Handlers for Real-Time UI Broadcasting
    # ---------------------------------------------------------
    async def _on_orchestrator_state_changed(self, topic: str, payload: Dict[str, Any]) -> None:
        self.ipc_server.broadcast_notification("ai.state_changed", payload)

    async def _on_approval_required(self, topic: str, payload: Dict[str, Any]) -> None:
        self.ipc_server.broadcast_notification("ai.approval_requested", payload)

    async def _on_step_event(self, topic: str, payload: Dict[str, Any]) -> None:
        self.ipc_server.broadcast_notification("ai.step_update", payload)

    async def _on_voice_event(self, topic: str, payload: Dict[str, Any]) -> None:
        self.ipc_server.broadcast_notification(topic, payload)

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

        # Shutdown voice pipeline
        try:
            await self.voice_mgr.shutdown()
        except Exception as e:
            logger.error("Error shutting down voice manager: %s", e)

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
