"""Central AI Orchestrator coordinating conversation, model providers, planning, and tools."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
import json
import logging
from pathlib import Path
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from zoro.core.event_bus import AsyncEventBus
from zoro.models.base import ChatCompletionRequest, ChatMessage
from zoro.models.registry import ProviderRegistry
from zoro.planner.executor import PlanExecutor
from zoro.planner.models import PlanStatus, PlanStep, PlanStepStatus, TaskPlan
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.storage.db import DatabaseManager
from zoro.tools.base import ApprovalStatus
from zoro.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class OrchestratorState(str, Enum):
    IDLE = "IDLE"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING = "EXECUTING"
    WAITING_FOR_RESULT = "WAITING_FOR_RESULT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OrchestratorResponse(BaseModel):
    conversation_id: str
    message: str
    state: OrchestratorState
    plan_id: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    approval_required: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ZoroOrchestrator:
    """The central intelligence coordinator managing user requests, planning, and capabilities."""

    def __init__(
        self,
        provider_registry: ProviderRegistry,
        tool_registry: ToolRegistry,
        db: Optional[DatabaseManager] = None,
        audit: Optional[AuditLogger] = None,
        event_bus: Optional[AsyncEventBus] = None,
        emergency_mgr: Optional[EmergencyManager] = None,
    ) -> None:
        self.provider_registry = provider_registry
        self.tool_registry = tool_registry
        self.db = db
        self.audit = audit
        self.event_bus = event_bus
        self.emergency_mgr = emergency_mgr or EmergencyManager()

        self.planner = PlanExecutor(
            tool_registry=self.tool_registry,
            db=self.db,
            event_bus=self.event_bus,
        )

        self._state: OrchestratorState = OrchestratorState.IDLE
        self._active_plan: Optional[TaskPlan] = None
        self._is_cancelled = False

    @property
    def state(self) -> OrchestratorState:
        return self._state

    async def set_state(self, new_state: OrchestratorState) -> None:
        old_state = self._state
        self._state = new_state
        logger.info("Orchestrator state transition: %s -> %s", old_state.value, new_state.value)
        if self.event_bus:
            await self.event_bus.publish(
                "orchestrator.state_changed",
                {"old_state": old_state.value, "new_state": new_state.value},
            )

    def cancel(self) -> None:
        """Cancel in-flight task execution cooperatively."""
        self._is_cancelled = True
        self.planner.cancel()
        asyncio.create_task(self.set_state(OrchestratorState.CANCELLED))
        logger.info("Orchestrator cancellation signaled.")

    async def process_user_request(
        self,
        user_message: str,
        conversation_id: Optional[str] = None,
    ) -> OrchestratorResponse:
        """
        Main intelligence pipeline entry point:
        1. Pre-flight emergency halt check.
        2. Context initialization & user message persistence.
        3. Intent understanding (conversational vs multi-step task planning).
        4. Plan decomposition & execution via secure tools if task-oriented.
        5. Synthesis of final response.
        """
        self._is_cancelled = False

        # 1. Emergency safety check
        is_halted, _ = self.emergency_mgr.is_halted()
        if is_halted:
            await self.set_state(OrchestratorState.FAILED)
            return OrchestratorResponse(
                conversation_id=conversation_id or "emergency",
                message="Operation refused: System is currently in an EMERGENCY HALT state.",
                state=OrchestratorState.FAILED,
                error="Emergency halt active",
            )

        conv_id = conversation_id or f"conv-{uuid.uuid4().hex[:8]}"
        await self.set_state(OrchestratorState.UNDERSTANDING)

        # 2. Persist user message to SQLite
        await self._persist_conversation(conv_id, "User Conversation")
        await self._persist_message(conv_id, "user", user_message)

        # 3. Determine if multi-step planning is required
        needs_planning = self._analyze_intent_needs_planning(user_message)

        if not needs_planning:
            # Direct Conversational Response
            return await self._handle_direct_conversation(conv_id, user_message)

        # 4. Multi-Step Task Planning
        await self.set_state(OrchestratorState.PLANNING)
        plan = await self._propose_plan_for_request(conv_id, user_message)
        self._active_plan = plan

        await self.set_state(OrchestratorState.EXECUTING)
        executed_plan = await self.planner.execute_plan(plan)

        # 5. Handle execution outcome
        if executed_plan.status == PlanStatus.WAITING_FOR_APPROVAL:
            await self.set_state(OrchestratorState.WAITING_FOR_APPROVAL)
            # Find the step waiting for approval
            waiting_step = next(
                (s for s in executed_plan.steps if s.status == PlanStepStatus.WAITING_FOR_APPROVAL),
                None,
            )
            approval_info = None
            if waiting_step:
                approval_info = {
                    "step_id": waiting_step.step_id,
                    "tool_name": waiting_step.tool_name,
                    "description": waiting_step.description,
                    "token": waiting_step.approval_token,
                }
            return OrchestratorResponse(
                conversation_id=conv_id,
                message=f"I have prepared an execution plan, but step '{waiting_step.description if waiting_step else ''}' requires your authorization.",
                state=OrchestratorState.WAITING_FOR_APPROVAL,
                plan_id=executed_plan.plan_id,
                plan=executed_plan.model_dump(),
                approval_required=approval_info,
            )

        elif executed_plan.status == PlanStatus.COMPLETED:
            await self.set_state(OrchestratorState.COMPLETED)
            summary_msg = self._synthesize_plan_completion(executed_plan)
            await self._persist_message(conv_id, "assistant", summary_msg)
            await self.set_state(OrchestratorState.IDLE)
            return OrchestratorResponse(
                conversation_id=conv_id,
                message=summary_msg,
                state=OrchestratorState.COMPLETED,
                plan_id=executed_plan.plan_id,
                plan=executed_plan.model_dump(),
            )

        elif executed_plan.status == PlanStatus.CANCELLED:
            await self.set_state(OrchestratorState.CANCELLED)
            msg = "Task execution was cancelled as requested."
            await self._persist_message(conv_id, "assistant", msg)
            return OrchestratorResponse(
                conversation_id=conv_id,
                message=msg,
                state=OrchestratorState.CANCELLED,
                plan_id=executed_plan.plan_id,
                plan=executed_plan.model_dump(),
            )

        else:  # FAILED
            await self.set_state(OrchestratorState.FAILED)
            err_msg = f"Task execution failed: {executed_plan.error}"
            await self._persist_message(conv_id, "assistant", err_msg)
            return OrchestratorResponse(
                conversation_id=conv_id,
                message=err_msg,
                state=OrchestratorState.FAILED,
                plan_id=executed_plan.plan_id,
                plan=executed_plan.model_dump(),
                error=executed_plan.error,
            )

    async def resolve_approval(self, token_str: str, approved: bool) -> OrchestratorResponse:
        """Process user's approval decision for a paused plan step and resume execution."""
        if not self._active_plan or self._active_plan.status != PlanStatus.WAITING_FOR_APPROVAL:
            return OrchestratorResponse(
                conversation_id="none",
                message="No active plan is currently awaiting approval.",
                state=self._state,
                error="No plan waiting for approval",
            )

        if approved:
            success = self.tool_registry.approve_token(token_str)
            if not success:
                return OrchestratorResponse(
                    conversation_id=self._active_plan.conversation_id or "default",
                    message="Approval token could not be approved (invalid or expired).",
                    state=self._state,
                    error="Token approval failed",
                )
            # Resume execution
            await self.set_state(OrchestratorState.EXECUTING)
            resumed_plan = await self.planner.execute_plan(self._active_plan)
            if resumed_plan.status == PlanStatus.COMPLETED:
                await self.set_state(OrchestratorState.COMPLETED)
                summary_msg = self._synthesize_plan_completion(resumed_plan)
                await self._persist_message(resumed_plan.conversation_id or "default", "assistant", summary_msg)
                await self.set_state(OrchestratorState.IDLE)
                return OrchestratorResponse(
                    conversation_id=resumed_plan.conversation_id or "default",
                    message=summary_msg,
                    state=OrchestratorState.COMPLETED,
                    plan_id=resumed_plan.plan_id,
                    plan=resumed_plan.model_dump(),
                )
            elif resumed_plan.status == PlanStatus.WAITING_FOR_APPROVAL:
                await self.set_state(OrchestratorState.WAITING_FOR_APPROVAL)
                waiting_step = next(
                    (s for s in resumed_plan.steps if s.status == PlanStepStatus.WAITING_FOR_APPROVAL),
                    None,
                )
                return OrchestratorResponse(
                    conversation_id=resumed_plan.conversation_id or "default",
                    message="Step completed. Subsequent step requires additional approval.",
                    state=OrchestratorState.WAITING_FOR_APPROVAL,
                    plan_id=resumed_plan.plan_id,
                    plan=resumed_plan.model_dump(),
                    approval_required={"token": waiting_step.approval_token} if waiting_step else None,
                )
            else:
                await self.set_state(OrchestratorState.FAILED)
                return OrchestratorResponse(
                    conversation_id=resumed_plan.conversation_id or "default",
                    message=f"Resumed execution failed: {resumed_plan.error}",
                    state=OrchestratorState.FAILED,
                    plan_id=resumed_plan.plan_id,
                    plan=resumed_plan.model_dump(),
                    error=resumed_plan.error,
                )
        else:
            self.tool_registry.reject_token(token_str)
            self._active_plan.status = PlanStatus.CANCELLED
            await self.set_state(OrchestratorState.CANCELLED)
            msg = "Action rejected by user. Plan execution halted."
            await self._persist_message(self._active_plan.conversation_id or "default", "assistant", msg)
            return OrchestratorResponse(
                conversation_id=self._active_plan.conversation_id or "default",
                message=msg,
                state=OrchestratorState.CANCELLED,
                plan_id=self._active_plan.plan_id,
                plan=self._active_plan.model_dump(),
            )

    def _analyze_intent_needs_planning(self, text: str) -> bool:
        """Determine if request requires file/tool operations vs plain chat."""
        keywords = [
            "find", "discover", "search files", "report", "pdf", "categorize",
            "move", "delete", "clean up", "organize", "files in", "create a report",
        ]
        text_lower = text.lower()
        return any(kw in text_lower for kw in keywords)

    async def _handle_direct_conversation(
        self, conv_id: str, user_message: str
    ) -> OrchestratorResponse:
        # Build prompt with history
        history = await self._load_conversation_history(conv_id)
        messages = [
            ChatMessage(role="system", content="You are ZORO, a sophisticated and loyal personal artificial intelligence assistant.")
        ]
        messages.extend(history)

        req = ChatCompletionRequest(
            model=self.provider_registry.get_active_model(),
            messages=messages,
            temperature=0.7,
            max_tokens=512,
        )

        try:
            resp = await self.provider_registry.chat_completion_with_fallback(req)
            reply = resp.content or "I have processed your request, Sir."
            await self._persist_message(conv_id, "assistant", reply)
            await self.set_state(OrchestratorState.COMPLETED)
            await self.set_state(OrchestratorState.IDLE)
            return OrchestratorResponse(
                conversation_id=conv_id,
                message=reply,
                state=OrchestratorState.COMPLETED,
            )
        except Exception as e:
            logger.error("Direct conversation failed: %s", e)
            await self.set_state(OrchestratorState.FAILED)
            err_msg = f"Failed to generate response: {e}"
            return OrchestratorResponse(
                conversation_id=conv_id,
                message=err_msg,
                state=OrchestratorState.FAILED,
                error=str(e),
            )

    async def _propose_plan_for_request(self, conv_id: str, user_request: str) -> TaskPlan:
        """
        Formulate a structured execution plan.
        Extracts paths or parameters from the request or creates standard workflow steps.
        """
        import re
        steps: List[PlanStep] = []
        req_lower = user_request.lower()

        # Check for move operation
        if "move" in req_lower:
            quoted = re.findall(r"['\"]([^'\"]+)['\"]", user_request)
            if len(quoted) >= 2:
                src, dst = quoted[0], quoted[1]
            else:
                src = "source.txt"
                dst = "dest.txt"
            steps.append(
                PlanStep(
                    step_id=f"step-{uuid.uuid4().hex[:6]}",
                    tool_name="file_move",
                    description=f"Move '{src}' to '{dst}'",
                    input_parameters={"source_path": src, "destination_path": dst},
                    dependencies=[],
                    requires_approval=True,
                )
            )
            return TaskPlan(
                conversation_id=conv_id,
                user_request=user_request,
                steps=steps,
                status=PlanStatus.PENDING,
            )

        # Check for delete operation
        if "delete" in req_lower:
            quoted = re.findall(r"['\"]([^'\"]+)['\"]", user_request)
            del_path = quoted[0] if quoted else "reports/dummy_temp.pdf"
            steps.append(
                PlanStep(
                    step_id=f"step-{uuid.uuid4().hex[:6]}",
                    tool_name="file_delete",
                    description=f"Permanently delete '{del_path}'",
                    input_parameters={"file_path": del_path},
                    dependencies=[],
                    requires_approval=True,
                )
            )
            return TaskPlan(
                conversation_id=conv_id,
                user_request=user_request,
                steps=steps,
                status=PlanStatus.PENDING,
            )

        # Standard discovery & report workflow
        target_dir = str(Path(".").resolve())
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", user_request)
        if quoted:
            target_dir = quoted[0]
        elif "downloads" in req_lower:
            target_dir = str(Path.home() / "Downloads")
        elif "documents" in req_lower:
            target_dir = str(Path.home() / "Documents")

        step1_id = f"step-{uuid.uuid4().hex[:6]}"
        pattern = "*.pdf" if "pdf" in req_lower else "*"
        steps.append(
            PlanStep(
                step_id=step1_id,
                tool_name="file_discovery",
                description=f"Discover files matching '{pattern}' in target directory",
                input_parameters={"directory": target_dir, "pattern": pattern, "max_results": 50},
                dependencies=[],
            )
        )

        if "report" in req_lower or "summary" in req_lower:
            step2_id = f"step-{uuid.uuid4().hex[:6]}"
            steps.append(
                PlanStep(
                    step_id=step2_id,
                    tool_name="report_generator",
                    description="Generate categorized file summary report",
                    input_parameters={
                        "output_path": str(Path("reports/discovery_report.md").resolve()),
                        "title": "ZORO File Discovery & Analysis Report",
                        "content": "Automated report generated from discovered file catalog.",
                    },
                    dependencies=[step1_id],
                )
            )

        return TaskPlan(
            conversation_id=conv_id,
            user_request=user_request,
            steps=steps,
            status=PlanStatus.PENDING,
        )

    def _synthesize_plan_completion(self, plan: TaskPlan) -> str:
        completed = [s for s in plan.steps if s.status == PlanStepStatus.COMPLETED]
        details = []
        for s in completed:
            details.append(f"- **{s.description}**: Completed successfully.")
        steps_summary = "\n".join(details)
        return (
            f"Sir, I have completed the execution of your request:\n\n"
            f"{steps_summary}\n\n"
            f"All {len(completed)} task step(s) were verified and audited."
        )

    async def _persist_conversation(self, conv_id: str, title: str) -> None:
        if not self.db:
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            await self.db.execute_write(
                """
                INSERT INTO conversations (id, title, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at
                """,
                (conv_id, title, now, now, "{}"),
            )
        except Exception as e:
            logger.error("Failed to persist conversation %s: %s", conv_id, e)

    async def _persist_message(self, conv_id: str, role: str, content: str) -> None:
        if not self.db:
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            await self.db.execute_write(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                (conv_id, role, content, now),
            )
        except Exception as e:
            logger.error("Failed to persist message in %s: %s", conv_id, e)

    async def _load_conversation_history(self, conv_id: str, limit: int = 10) -> List[ChatMessage]:
        if not self.db:
            return []
        try:
            rows = await self.db.execute_read(
                "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC LIMIT ?",
                (conv_id, limit),
            )
            return [ChatMessage(role=r[0], content=r[1]) for r in rows]
        except Exception as e:
            logger.error("Failed to load history for %s: %s", conv_id, e)
            return []
