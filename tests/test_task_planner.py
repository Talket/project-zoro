"""Tests for Multi-Step Task Planner (DAG dependency resolution, validation, execution)."""

import pytest
from pathlib import Path

from zoro.core.event_bus import AsyncEventBus
from zoro.planner.graph import (
    CircularDependencyError,
    DependencyGraph,
    InvalidDependencyError,
)
from zoro.planner.models import PlanStatus, PlanStep, PlanStepStatus, TaskPlan
from zoro.planner.validator import PlanValidationError, PlanValidator
from zoro.planner.executor import PlanExecutor
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.tools.builtin.file_tools import (
    FileDeleteTool,
    FileDiscoveryTool,
    FileMoveTool,
    ReportGeneratorTool,
)
from zoro.tools.registry import ToolRegistry


def test_dependency_graph_topological_sort():
    s1 = PlanStep(step_id="step-1", tool_name="file_discovery", description="step 1")
    s2 = PlanStep(step_id="step-2", tool_name="report_generator", description="step 2", dependencies=["step-1"])
    s3 = PlanStep(step_id="step-3", tool_name="file_move", description="step 3", dependencies=["step-2"])

    order = DependencyGraph.resolve_execution_order([s3, s1, s2])
    assert order == ["step-1", "step-2", "step-3"]


def test_dependency_graph_cycle_detection():
    # Circular dependency A -> B -> A
    s1 = PlanStep(step_id="step-A", tool_name="tool", description="A", dependencies=["step-B"])
    s2 = PlanStep(step_id="step-B", tool_name="tool", description="B", dependencies=["step-A"])

    with pytest.raises(CircularDependencyError):
        DependencyGraph.resolve_execution_order([s1, s2])

    # Self-cycle A -> A
    s3 = PlanStep(step_id="step-self", tool_name="tool", description="self", dependencies=["step-self"])
    with pytest.raises(CircularDependencyError):
        DependencyGraph.resolve_execution_order([s3])


def test_dependency_graph_missing_dependency():
    s1 = PlanStep(step_id="step-1", tool_name="tool", description="1", dependencies=["step-ghost"])
    with pytest.raises(InvalidDependencyError, match="non-existent dependency"):
        DependencyGraph.resolve_execution_order([s1])


def test_plan_validator_limits_and_rules():
    reg = ToolRegistry()
    reg.register(FileDiscoveryTool())
    reg.register(FileMoveTool())
    validator = PlanValidator(reg)

    # Empty plan
    with pytest.raises(PlanValidationError, match="at least one step"):
        validator.validate_plan(TaskPlan(user_request="empty", steps=[]))

    # Exceeding MAX_STEPS (21 steps)
    too_many = [
        PlanStep(step_id=f"step-{i}", tool_name="file_discovery", description=f"s{i}")
        for i in range(25)
    ]
    with pytest.raises(PlanValidationError, match="exceeds maximum step limit"):
        validator.validate_plan(TaskPlan(user_request="big", steps=too_many))

    # Unregistered tool
    unregistered = [PlanStep(step_id="step-1", tool_name="nonexistent_tool", description="invalid")]
    with pytest.raises(PlanValidationError, match="unregistered tool"):
        validator.validate_plan(TaskPlan(user_request="invalid", steps=unregistered))

    # Auto tagging of requires_approval for sensitive tools
    sensitive_step = PlanStep(step_id="step-s", tool_name="file_move", description="move something")
    validator.validate_plan(TaskPlan(user_request="move", steps=[sensitive_step]))
    assert sensitive_step.requires_approval is True


@pytest.mark.asyncio
async def test_plan_executor_multi_step_flow(tmp_path):
    db_path = tmp_path / "plan_test.db"
    db = DatabaseManager(db_path=db_path)
    await db.initialize()

    reg = ToolRegistry(db=db)
    gate = PermissionGate()
    reg.register(FileDiscoveryTool(permission_gate=gate))
    reg.register(ReportGeneratorTool(permission_gate=gate))

    event_bus = AsyncEventBus()
    executor = PlanExecutor(tool_registry=reg, db=db, event_bus=event_bus)

    # Workspace files
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "sample1.txt").write_text("file 1")
    (ws / "sample2.txt").write_text("file 2")
    report_target = ws / "report.md"

    # Define plan: step 1 finds files, step 2 generates report
    s1 = PlanStep(
        step_id="step-disc",
        tool_name="file_discovery",
        description="Find text files",
        input_parameters={"directory": str(ws), "pattern": "*.txt"},
    )
    s2 = PlanStep(
        step_id="step-rep",
        tool_name="report_generator",
        description="Generate discovery report",
        input_parameters={
            "output_path": str(report_target),
            "title": "Discovery Report",
            "content": "Discovery completed successfully.",
        },
        dependencies=["step-disc"],
    )

    plan = TaskPlan(
        user_request="Scan workspace and write report",
        steps=[s1, s2],
    )

    executed_plan = await executor.execute_plan(plan)
    assert executed_plan.status == PlanStatus.COMPLETED
    assert s1.status == PlanStepStatus.COMPLETED
    assert s2.status == PlanStepStatus.COMPLETED
    assert report_target.exists()

    # Verify persistence in database
    plan_rows = await db.execute_read("SELECT status FROM task_plans WHERE id = ?", (plan.plan_id,))
    assert len(plan_rows) == 1
    assert plan_rows[0][0] == "COMPLETED"

    step_rows = await db.execute_read("SELECT id, status FROM task_steps WHERE plan_id = ?", (plan.plan_id,))
    assert len(step_rows) == 2

    await db.close()


@pytest.mark.asyncio
async def test_plan_executor_approval_pause_and_resume(tmp_path):
    db_path = tmp_path / "plan_approval.db"
    db = DatabaseManager(db_path=db_path)
    await db.initialize()

    reg = ToolRegistry(db=db)
    gate = PermissionGate()
    reg.register(FileMoveTool(permission_gate=gate))

    executor = PlanExecutor(tool_registry=reg, db=db)

    work_dir = tmp_path / "work"
    work_dir.mkdir()
    src = work_dir / "old_name.txt"
    src.write_text("rename me")
    dst = work_dir / "new_name.txt"

    step_move = PlanStep(
        step_id="step-move",
        tool_name="file_move",
        description="Move sensitive file",
        input_parameters={"source_path": str(src), "destination_path": str(dst)},
    )
    plan = TaskPlan(user_request="Move file", steps=[step_move])

    # First execution pauses for approval
    paused_plan = await executor.execute_plan(plan)
    assert paused_plan.status == PlanStatus.WAITING_FOR_APPROVAL
    assert step_move.status == PlanStepStatus.WAITING_FOR_APPROVAL
    assert step_move.approval_token is not None
    assert src.exists()
    assert not dst.exists()

    # User approves token
    approved = reg.approve_token(step_move.approval_token)
    assert approved is True

    # Resume execution
    resumed_plan = await executor.execute_plan(paused_plan)
    assert resumed_plan.status == PlanStatus.COMPLETED
    assert step_move.status == PlanStepStatus.COMPLETED
    assert not src.exists()
    assert dst.exists()

    await db.close()


@pytest.mark.asyncio
async def test_plan_executor_cancellation(tmp_path):
    reg = ToolRegistry()
    reg.register(FileDiscoveryTool())
    executor = PlanExecutor(tool_registry=reg)

    plan = TaskPlan(
        user_request="Cancel test",
        steps=[
            PlanStep(step_id="s1", tool_name="file_discovery", description="step 1", input_parameters={"directory": str(tmp_path)}),
            PlanStep(step_id="s2", tool_name="file_discovery", description="step 2", input_parameters={"directory": str(tmp_path)}, dependencies=["s1"]),
        ],
    )
    executor.cancel()
    res = await executor.execute_plan(plan)
    assert res.status == PlanStatus.CANCELLED


@pytest.mark.asyncio
async def test_plan_executor_dependency_failure_and_retries(tmp_path):
    reg = ToolRegistry()
    reg.register(FileDiscoveryTool())
    reg.register(ReportGeneratorTool())
    executor = PlanExecutor(tool_registry=reg)

    # Step 1 points to non-existent directory -> fails after retries
    s1 = PlanStep(
        step_id="step-fail",
        tool_name="file_discovery",
        description="Failing step",
        input_parameters={"directory": str(tmp_path / "does_not_exist")},
        max_retries=1,
    )
    s2 = PlanStep(
        step_id="step-skip",
        tool_name="report_generator",
        description="Dependent step",
        input_parameters={"output_path": str(tmp_path / "rep.md"), "title": "T", "content": "C"},
        dependencies=["step-fail"],
    )

    plan = TaskPlan(user_request="Fail test", steps=[s1, s2])
    res = await executor.execute_plan(plan)
    assert res.status == PlanStatus.FAILED
    assert s1.status == PlanStepStatus.FAILED
    assert s1.retry_count == 2  # initial try + 1 retry = 2 attempts


def test_plan_executor_resolve_inputs():
    reg = ToolRegistry()
    executor = PlanExecutor(tool_registry=reg)

    step_map = {
        "step-1": PlanStep(
            step_id="step-1",
            tool_name="tool",
            description="d",
            output_data={"file_count": 42, "target": "reports/summary.md"},
        )
    }

    raw_inputs = {
        "count": "{{step-1.file_count}}",
        "path": "{{step-1.target}}",
        "static": "regular_value",
        "unmatched": "{{step-2.missing}}",
    }

    resolved = executor._resolve_inputs(raw_inputs, step_map)
    assert resolved["count"] == 42
    assert resolved["path"] == "reports/summary.md"
    assert resolved["static"] == "regular_value"
    assert resolved["unmatched"] == "{{step-2.missing}}"

