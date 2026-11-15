"""Asynchronous Multi-Step Plan Executor coordinating tool calls, approvals, and progress."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from zoro.core.event_bus import AsyncEventBus
from zoro.planner.graph import DependencyGraph
from zoro.planner.models import PlanStatus, PlanStep, PlanStepStatus, TaskPlan
from zoro.planner.validator import PlanValidator
from zoro.storage.db import DatabaseManager
from zoro.tools.base import ApprovalStatus, ToolContext, ToolResult
from zoro.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class PlanExecutor:
    """Executes validated multi-step plans with approval gating, retries, and persistence."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        db: Optional[DatabaseManager] = None,
        event_bus: Optional[AsyncEventBus] = None,
    ) -> None:
        self.registry = tool_registry
        self.db = db
        self.event_bus = event_bus
        self.validator = PlanValidator(tool_registry)
        self._is_cancelled = False

    def cancel(self) -> None:
        """Signal cooperative cancellation of active plan execution."""
        self._is_cancelled = True
        logger.info("Plan execution cancellation requested.")

    def reset_cancellation(self) -> None:
        """Reset cancellation state for a new plan execution."""
        self._is_cancelled = False

    async def execute_plan(self, plan: TaskPlan) -> TaskPlan:
        """
        Execute all steps in topological dependency order.
        Stops on unapproved sensitive steps (waiting for user approval) or step failures.
        """
        if self._is_cancelled:
            plan.status = PlanStatus.CANCELLED
            self._cancel_remaining_steps(plan, [s.step_id for s in plan.steps])
            await self._persist_plan(plan)
            await self._emit_event("plan.cancelled", plan)
            return plan

        plan.status = PlanStatus.VALIDATING
        await self._persist_plan(plan)

        # 1. Validate plan structure
        try:
            execution_order = self.validator.validate_plan(plan)
        except Exception as val_err:
            plan.status = PlanStatus.FAILED
            plan.error = f"Validation failed: {val_err}"
            await self._persist_plan(plan)
            return plan

        plan.status = PlanStatus.EXECUTING
        await self._persist_plan(plan)
        await self._emit_event("plan.started", plan)

        step_map: Dict[str, PlanStep] = {s.step_id: s for s in plan.steps}

        # 2. Iterate in topological order
        for step_id in execution_order:
            if self._is_cancelled:
                plan.status = PlanStatus.CANCELLED
                self._cancel_remaining_steps(plan, execution_order)
                await self._persist_plan(plan)
                await self._emit_event("plan.cancelled", plan)
                return plan

            step = step_map[step_id]

            # If step was already completed (e.g. resuming after approval), skip
            if step.status == PlanStepStatus.COMPLETED:
                continue

            # Verify all dependencies completed successfully
            for dep_id in step.dependencies:
                dep_step = step_map[dep_id]
                if dep_step.status != PlanStepStatus.COMPLETED:
                    step.status = PlanStepStatus.SKIPPED
                    step.error = f"Dependency '{dep_id}' did not complete successfully (Status: {dep_step.status.value})."
                    plan.status = PlanStatus.FAILED
                    plan.error = f"Plan stopped: Dependency '{dep_id}' failed."
                    await self._persist_step(plan.plan_id, step)
                    await self._persist_plan(plan)
                    await self._emit_event("plan.failed", plan)
                    return plan

            # 3. Check for human approval requirement
            if step.requires_approval:
                if not step.approval_token:
                    # Create approval request token
                    token = self.registry.create_approval_token(
                        tool_name=step.tool_name,
                        description=f"Approval needed for step '{step.description}'",
                        step_id=step.step_id,
                    )
                    step.approval_token = token.token
                    step.status = PlanStepStatus.WAITING_FOR_APPROVAL
                    plan.status = PlanStatus.WAITING_FOR_APPROVAL
                    await self._persist_step(plan.plan_id, step)
                    await self._persist_plan(plan)
                    await self._emit_event("plan.approval_required", {
                        "plan_id": plan.plan_id,
                        "step_id": step.step_id,
                        "tool_name": step.tool_name,
                        "token": token.token,
                        "description": token.description,
                    })
                    return plan

                # Check if existing token has been approved
                token_obj = self.registry._approval_tokens.get(step.approval_token)
                if not token_obj or token_obj.status != ApprovalStatus.APPROVED:
                    step.status = PlanStepStatus.WAITING_FOR_APPROVAL
                    plan.status = PlanStatus.WAITING_FOR_APPROVAL
                    await self._persist_step(plan.plan_id, step)
                    await self._persist_plan(plan)
                    return plan

            # 4. Resolve input parameters from prior step outputs
            resolved_inputs = self._resolve_inputs(step.input_parameters, step_map)

            # 5. Execute step with retries
            step.status = PlanStepStatus.EXECUTING
            step.started_at = datetime.now(timezone.utc).isoformat()
            await self._persist_step(plan.plan_id, step)
            await self._emit_event("step.started", step)

            success = False
            while step.retry_count <= step.max_retries and not success:
                if self._is_cancelled:
                    step.status = PlanStepStatus.CANCELLED
                    plan.status = PlanStatus.CANCELLED
                    await self._persist_step(plan.plan_id, step)
                    await self._persist_plan(plan)
                    return plan

                context = ToolContext(
                    caller=f"planner:{plan.plan_id}",
                    step_id=step.step_id,
                    approval_token=step.approval_token,
                )

                result: ToolResult = await self.registry.execute_tool(
                    tool_name=step.tool_name,
                    arguments=resolved_inputs,
                    context=context,
                )

                if result.success:
                    step.status = PlanStepStatus.COMPLETED
                    step.output_data = result.data
                    step.error = None
                    step.completed_at = datetime.now(timezone.utc).isoformat()
                    success = True
                else:
                    step.retry_count += 1
                    step.error = result.error
                    if step.retry_count <= step.max_retries:
                        logger.warning(
                            "Step '%s' failed (%s). Retrying (%d/%d)...",
                            step.step_id,
                            result.error,
                            step.retry_count,
                            step.max_retries,
                        )
                        await asyncio.sleep(0.5)

            if not success:
                step.status = PlanStepStatus.FAILED
                step.completed_at = datetime.now(timezone.utc).isoformat()
                plan.status = PlanStatus.FAILED
                plan.error = f"Step '{step.step_id}' ({step.description}) failed: {step.error}"
                await self._persist_step(plan.plan_id, step)
                await self._persist_plan(plan)
                await self._emit_event("step.failed", step)
                await self._emit_event("plan.failed", plan)
                return plan

            await self._persist_step(plan.plan_id, step)
            await self._emit_event("step.completed", step)

        # All steps completed successfully!
        plan.status = PlanStatus.COMPLETED
        plan.completed_at = datetime.now(timezone.utc).isoformat()
        plan.updated_at = datetime.now(timezone.utc).isoformat()
        await self._persist_plan(plan)
        await self._emit_event("plan.completed", plan)
        return plan

    def _resolve_inputs(self, inputs: Dict[str, Any], step_map: Dict[str, PlanStep]) -> Dict[str, Any]:
        """
        Resolve placeholders like '{{step-id.output_key}}' with actual data from prior steps.
        """
        resolved = {}
        for k, v in inputs.items():
            if isinstance(v, str) and v.startswith("{{") and v.endswith("}}"):
                expr = v[2:-2].strip()
                if "." in expr:
                    target_step_id, target_key = expr.split(".", 1)
                    if target_step_id in step_map and step_map[target_step_id].output_data:
                        resolved[k] = step_map[target_step_id].output_data.get(target_key, v)
                        continue
            resolved[k] = v
        return resolved

    def _cancel_remaining_steps(self, plan: TaskPlan, execution_order: List[str]) -> None:
        for s in plan.steps:
            if s.status in (PlanStepStatus.PENDING, PlanStepStatus.WAITING_FOR_APPROVAL):
                s.status = PlanStepStatus.CANCELLED

    async def _persist_plan(self, plan: TaskPlan) -> None:
        if not self.db:
            return
        try:
            await self.db.execute_write(
                """
                INSERT INTO task_plans (id, conversation_id, user_request, status, plan_json, created_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    plan_json=excluded.plan_json,
                    updated_at=excluded.updated_at,
                    completed_at=excluded.completed_at
                """,
                (
                    plan.plan_id,
                    plan.conversation_id,
                    plan.user_request,
                    plan.status.value,
                    plan.model_dump_json(),
                    plan.created_at,
                    plan.updated_at,
                    plan.completed_at,
                ),
            )
        except Exception as e:
            logger.error("Failed to persist task plan %s: %s", plan.plan_id, e)

    async def _persist_step(self, plan_id: str, step: PlanStep) -> None:
        if not self.db:
            return
        try:
            await self.db.execute_write(
                """
                INSERT INTO task_steps (id, plan_id, step_index, description, tool_name, input_json, output_json, status, error, requires_approval, approval_token, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    output_json=excluded.output_json,
                    status=excluded.status,
                    error=excluded.error,
                    requires_approval=excluded.requires_approval,
                    approval_token=excluded.approval_token,
                    started_at=excluded.started_at,
                    completed_at=excluded.completed_at
                """,
                (
                    step.step_id,
                    plan_id,
                    step.step_index,
                    step.description,
                    step.tool_name,
                    json.dumps(step.input_parameters),
                    json.dumps(step.output_data) if step.output_data else None,
                    step.status.value,
                    step.error,
                    1 if step.requires_approval else 0,
                    step.approval_token,
                    step.started_at,
                    step.completed_at,
                ),
            )
        except Exception as e:
            logger.error("Failed to persist step %s: %s", step.step_id, e)

    async def _emit_event(self, event_type: str, data: Any) -> None:
        if self.event_bus:
            payload = data.model_dump() if hasattr(data, "model_dump") else data
            await self.event_bus.publish(event_type, payload)
