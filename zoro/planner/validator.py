"""Plan validation subsystem enforcing tool existence, step bounds, and permission requirements."""

from __future__ import annotations

import logging
from typing import List, Optional
from zoro.planner.graph import CircularDependencyError, DependencyGraph, InvalidDependencyError
from zoro.planner.models import TaskPlan
from zoro.tools.base import ToolPermissionTier
from zoro.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class PlanValidationError(Exception):
    """Raised when a proposed plan fails structural or security validation."""
    pass


class PlanValidator:
    """Validates proposed task plans against tool availability, DAG cycles, and security policies."""

    MAX_STEPS: int = 20

    def __init__(self, tool_registry: ToolRegistry) -> None:
        self.registry = tool_registry

    def validate_plan(self, plan: TaskPlan) -> List[str]:
        """
        Validate plan structure and security rules.
        Returns the resolved topological execution order of step_ids.
        Raises PlanValidationError if the plan is rejected.
        """
        if not plan.steps:
            raise PlanValidationError("Task plan must contain at least one step.")

        if len(plan.steps) > self.MAX_STEPS:
            raise PlanValidationError(
                f"Plan exceeds maximum step limit ({len(plan.steps)} > {self.MAX_STEPS}). "
                "Rejecting potentially uncontrolled recursive plan."
            )

        # 1. Validate tool existence and configure approval requirements
        for i, step in enumerate(plan.steps):
            step.step_index = i
            try:
                tool = self.registry.get_tool(step.tool_name)
            except ValueError:
                raise PlanValidationError(
                    f"Step '{step.step_id}' ({step.description}) references unregistered tool '{step.tool_name}'."
                )

            # Security rule: AI proposed plans cannot bypass approval
            if tool.permission_tier in (
                ToolPermissionTier.SENSITIVE,
                ToolPermissionTier.DESTRUCTIVE,
                ToolPermissionTier.SYSTEM_CRITICAL,
            ):
                step.requires_approval = True

        # 2. Validate DAG dependency graph and cycle freedom
        try:
            topological_order = DependencyGraph.resolve_execution_order(plan.steps)
        except (CircularDependencyError, InvalidDependencyError) as dep_err:
            raise PlanValidationError(f"Invalid plan dependency structure: {dep_err}") from dep_err

        return topological_order
