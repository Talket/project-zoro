"""Directed Acyclic Graph (DAG) dependency resolution and cycle detection for task plans."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Dict, List, Set
from zoro.planner.models import PlanStep


class CircularDependencyError(Exception):
    """Raised when a task plan contains a circular dependency cycle."""
    pass


class InvalidDependencyError(Exception):
    """Raised when a step references a non-existent dependency step_id."""
    pass


class DependencyGraph:
    """Validates step dependency DAGs and computes topological execution orders."""

    @classmethod
    def resolve_execution_order(cls, steps: List[PlanStep]) -> List[str]:
        """
        Validate dependencies and compute topological sort order using Kahn's algorithm.
        Returns ordered list of step_ids.
        Raises CircularDependencyError if a cycle is present.
        Raises InvalidDependencyError if a dependency ID does not exist.
        """
        step_ids = {s.step_id for s in steps}
        in_degree: Dict[str, int] = {s.step_id: 0 for s in steps}
        adj_list: Dict[str, List[str]] = defaultdict(list)

        for step in steps:
            for dep_id in step.dependencies:
                if dep_id not in step_ids:
                    raise InvalidDependencyError(
                        f"Step '{step.step_id}' references non-existent dependency '{dep_id}'."
                    )
                if dep_id == step.step_id:
                    raise CircularDependencyError(
                        f"Step '{step.step_id}' directly depends on itself (self-cycle)."
                    )
                # dep_id must run before step.step_id
                adj_list[dep_id].append(step.step_id)
                in_degree[step.step_id] += 1

        # Kahn's algorithm
        queue = deque([s_id for s_id, deg in in_degree.items() if deg == 0])
        ordered: List[str] = []

        while queue:
            curr_id = queue.popleft()
            ordered.append(curr_id)

            for neighbor in adj_list[curr_id]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(ordered) != len(steps):
            cycle_steps = [s_id for s_id, deg in in_degree.items() if deg > 0]
            raise CircularDependencyError(
                f"Circular dependency cycle detected among steps: {cycle_steps}"
            )

        return ordered
