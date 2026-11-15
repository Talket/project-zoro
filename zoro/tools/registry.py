"""Central Secure Tool Registry coordinating tool validation, permissions, and execution."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
import time
from typing import Any, Dict, List, Optional, Type
from pydantic import BaseModel, ValidationError

from zoro.security.audit import AuditLogger
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.tools.base import (
    ApprovalStatus,
    ApprovalToken,
    BaseTool,
    ToolContext,
    ToolPermissionTier,
    ToolResult,
)

logger = logging.getLogger(__name__)


class ToolRegistry:
    """Secure Tool Registry enforcing permission gates, input validation, and replay protection."""

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        audit: Optional[AuditLogger] = None,
        permission_gate: Optional[PermissionGate] = None,
    ) -> None:
        self.db = db
        self.audit = audit
        self.gate = permission_gate or PermissionGate()
        self._tools: Dict[str, BaseTool] = {}
        self._approval_tokens: Dict[str, ApprovalToken] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool with name '{tool.name}' is already registered.")
        self._tools[tool.name] = tool
        logger.info("Registered tool '%s' (Tier: %s)", tool.name, tool.permission_tier.value)

    def unregister(self, tool_name: str) -> None:
        self._tools.pop(tool_name, None)

    def get_tool(self, tool_name: str) -> BaseTool:
        if tool_name not in self._tools:
            raise ValueError(f"Tool '{tool_name}' is not registered.")
        return self._tools[tool_name]

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "title": t.title,
                "description": t.description,
                "permission_tier": t.permission_tier.value,
                "timeout_seconds": t.timeout_seconds,
            }
            for t in self._tools.values()
        ]

    def get_schemas_for_provider(self) -> List[Dict[str, Any]]:
        """Return function definitions for LLM tool calling."""
        return [tool.get_json_schema() for tool in self._tools.values()]

    def create_approval_token(
        self,
        tool_name: str,
        description: str,
        step_id: Optional[str] = None,
    ) -> ApprovalToken:
        tool = self.get_tool(tool_name)
        token = ApprovalToken(
            tool_name=tool_name,
            permission_tier=tool.permission_tier,
            description=description,
            step_id=step_id,
        )
        self._approval_tokens[token.token] = token
        logger.info(
            "Created approval request token %s for tool '%s' (Tier: %s)",
            token.token[:8],
            tool_name,
            tool.permission_tier.value,
        )
        return token

    def approve_token(self, token_str: str) -> bool:
        """User or owner authorizes the action token."""
        if token_str not in self._approval_tokens:
            return False
        token = self._approval_tokens[token_str]
        now = datetime.now(timezone.utc).timestamp()
        if now > token.expires_at_epoch:
            token.status = ApprovalStatus.EXPIRED
            return False
        if token.status != ApprovalStatus.PENDING:
            return False
        token.status = ApprovalStatus.APPROVED
        logger.info("Approval token %s was APPROVED.", token_str[:8])
        return True

    def reject_token(self, token_str: str) -> bool:
        if token_str not in self._approval_tokens:
            return False
        token = self._approval_tokens[token_str]
        token.status = ApprovalStatus.REJECTED
        logger.info("Approval token %s was REJECTED.", token_str[:8])
        return True

    def _validate_approval(self, tool: BaseTool, context: ToolContext) -> None:
        """
        Verify that an approval token is valid, approved, unexpired, and not replayed.
        Enforces single-use replay protection by immediately setting status to CONSUMED.
        """
        if tool.permission_tier in (
            ToolPermissionTier.SENSITIVE,
            ToolPermissionTier.DESTRUCTIVE,
            ToolPermissionTier.SYSTEM_CRITICAL,
        ):
            if not context.approval_token:
                raise PermissionError(
                    f"Tool '{tool.name}' requires explicit approval (Tier: {tool.permission_tier.value}), "
                    "but no approval token was provided."
                )

            token = self._approval_tokens.get(context.approval_token)
            if not token:
                raise PermissionError("Invalid or unknown approval token.")

            # Check expiration
            now = datetime.now(timezone.utc).timestamp()
            if now > token.expires_at_epoch:
                token.status = ApprovalStatus.EXPIRED
                raise PermissionError("Approval token has expired.")

            # Check status
            if token.status == ApprovalStatus.CONSUMED:
                raise PermissionError("Replay detected! Approval token has already been consumed.")
            if token.status == ApprovalStatus.REJECTED:
                raise PermissionError("Approval token was rejected by user.")
            if token.status != ApprovalStatus.APPROVED:
                raise PermissionError(f"Approval token is not approved (Current status: {token.status.value}).")

            # Check tool identity match
            if token.tool_name != tool.name:
                raise PermissionError(
                    f"Approval token mismatch: token issued for '{token.tool_name}', attempted use with '{tool.name}'."
                )

            # Consume token immediately (Replay Protection)
            token.status = ApprovalStatus.CONSUMED
            logger.info("Approval token %s consumed successfully.", token.token[:8])

    async def execute_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        context: Optional[ToolContext] = None,
    ) -> ToolResult:
        """
        Execute tool through security evaluation, schema validation, and audit logging.
        """
        ctx = context or ToolContext()
        start_time = time.perf_counter()

        # 1. Unregistered tool rejection
        if tool_name not in self._tools:
            err_msg = f"Rejection: Tool '{tool_name}' is not registered."
            await self._record_execution(tool_name, ctx.step_id, arguments, None, "DENIED", err_msg, 0.0)
            return ToolResult(success=False, error=err_msg)

        tool = self._tools[tool_name]

        # 2. Permission evaluation and approval validation
        try:
            self._validate_approval(tool, ctx)
        except PermissionError as p_err:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            await self._record_execution(tool_name, ctx.step_id, arguments, None, "DENIED", str(p_err), duration_ms)
            return ToolResult(success=False, error=str(p_err), execution_duration_ms=duration_ms)

        # 3. Input schema validation
        try:
            validated_input = tool.input_schema.model_validate(arguments)
        except ValidationError as val_err:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Invalid arguments for tool '{tool_name}': {val_err}"
            await self._record_execution(tool_name, ctx.step_id, arguments, None, "FAILED", err_msg, duration_ms)
            return ToolResult(success=False, error=err_msg, execution_duration_ms=duration_ms)

        # 4. Timed execution
        try:
            result_model = await asyncio.wait_for(
                tool.execute(validated_input, ctx),
                timeout=tool.timeout_seconds,
            )
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

            # 5. Output schema validation
            if not isinstance(result_model, tool.output_schema):
                err_msg = f"Tool '{tool_name}' returned invalid output type: {type(result_model)}"
                await self._record_execution(tool_name, ctx.step_id, arguments, None, "FAILED", err_msg, duration_ms)
                return ToolResult(success=False, error=err_msg, execution_duration_ms=duration_ms)

            result_data = result_model.model_dump()
            await self._record_execution(tool_name, ctx.step_id, arguments, result_data, "SUCCESS", None, duration_ms)
            return ToolResult(success=True, data=result_data, execution_duration_ms=duration_ms)

        except asyncio.TimeoutError:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Tool '{tool_name}' execution timed out after {tool.timeout_seconds}s."
            await self._record_execution(tool_name, ctx.step_id, arguments, None, "FAILED", err_msg, duration_ms)
            return ToolResult(success=False, error=err_msg, execution_duration_ms=duration_ms)

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            err_msg = f"Execution error in tool '{tool_name}': {exc}"
            await self._record_execution(tool_name, ctx.step_id, arguments, None, "FAILED", err_msg, duration_ms)
            return ToolResult(success=False, error=err_msg, execution_duration_ms=duration_ms)

    async def _record_execution(
        self,
        tool_name: str,
        step_id: Optional[str],
        input_data: Dict[str, Any],
        output_data: Optional[Dict[str, Any]],
        status: str,
        error: Optional[str],
        duration_ms: float,
    ) -> None:
        """Record execution to tool_executions and cryptographic audit log."""
        import json

        # SQLite tool_executions table
        if self.db:
            try:
                await self.db.execute_write(
                    """
                    INSERT INTO tool_executions (tool_name, step_id, input_json, output_json, status, error, duration_ms, executed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tool_name,
                        step_id,
                        json.dumps(input_data),
                        json.dumps(output_data) if output_data else None,
                        status,
                        error,
                        duration_ms,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
            except Exception as e:
                logger.error("Failed to record tool execution in DB: %s", e)

        # Chained HMAC audit log
        if self.audit:
            try:
                await self.audit.log_event(
                    actor="ToolRegistry",
                    action=f"TOOL_EXECUTE_{status}",
                    resource=tool_name,
                    details={
                        "step_id": step_id,
                        "status": status,
                        "error": error,
                        "duration_ms": duration_ms,
                    },
                )
            except Exception as e:
                logger.error("Failed to log audit event for tool: %s", e)
