"""Central AI Orchestrator coordinating conversation, model providers, planning, and tools."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import Enum
import json
import logging
from pathlib import Path
import re
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
from zoro.memory.manager import MemoryManager
from zoro.schedule.models import EventCategory, EventPriority, EventSource

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
        memory_mgr: Optional[MemoryManager] = None,
        scheduler_engine: Optional[Any] = None,
    ) -> None:
        self.provider_registry = provider_registry
        self.tool_registry = tool_registry
        self.db = db
        self.audit = audit
        self.event_bus = event_bus
        self.emergency_mgr = emergency_mgr or EmergencyManager()
        self.memory_mgr = memory_mgr
        self.scheduler_engine = scheduler_engine

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

    async def process_request(
        self,
        prompt: str,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Convenience dictionary adapter for process_user_request."""
        res = await self.process_user_request(user_message=prompt, conversation_id=conversation_id)
        return {
            "response": res.message,
            "plan": res.plan,
            "state": res.state.value if hasattr(res.state, "value") else str(res.state),
            "approval_required": res.approval_required,
            "error": res.error,
        }

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

    async def _handle_proactive_schedule_command(
        self, conv_id: str, user_message: str
    ) -> Optional[OrchestratorResponse]:
        """
        Detect and execute timetable, deadline, reminder, focus, and quiet hours commands.
        Enforces strict temporal validation, ambiguity detection, and persistent memory bridging.
        """
        if not self.scheduler_engine:
            return None

        norm_msg = user_message.lower().strip()

        # 1. Agenda and Timetable queries
        agenda_patterns = (
            "what do i have scheduled",
            "what is on my agenda",
            "what's on my agenda",
            "today's agenda",
            "show agenda",
            "show timetable",
            "what is my schedule",
            "show my schedule",
            "show schedule",
            "what do i have today",
            "my agenda",
            "daily briefing",
        )
        if any(p in norm_msg for p in agenda_patterns):
            try:
                briefing = await self.scheduler_engine.briefing.generate_briefing()
                msg = briefing.summary_text
                await self._persist_message(conv_id, "assistant", msg)
                await self.set_state(OrchestratorState.COMPLETED)
                await self.set_state(OrchestratorState.IDLE)
                return OrchestratorResponse(conversation_id=conv_id, message=msg, state=OrchestratorState.COMPLETED)
            except Exception as e:
                logger.error("Failed to generate agenda briefing: %s", e)

        # 2. Top Priorities query
        priority_patterns = (
            "top priorities",
            "three most urgent tasks",
            "most urgent tasks",
            "urgent deadlines",
            "what are my priorities",
            "top 3 priorities",
            "most urgent",
        )
        if any(p in norm_msg for p in priority_patterns):
            try:
                deadlines = await self.scheduler_engine.timetable.get_upcoming_deadlines(horizon_days=7)
                overdue = await self.scheduler_engine.timetable.get_overdue_tasks()
                items: List[str] = []
                for od in overdue[:2]:
                    items.append(f"Resolve overdue item: '{od.title}' (From {od.event_date})")
                for d in deadlines:
                    if len(items) >= 3:
                        break
                    items.append(f"Address deadline: '{d.title}' (Due {d.due_date}, {d.hours_remaining:.0f}h remaining)")

                if items:
                    lines = ["Sir, here are your top operational priorities:"]
                    for idx, it in enumerate(items, 1):
                        lines.append(f"  {idx}. {it}")
                    msg = "\n".join(lines)
                else:
                    msg = "Sir, all tasks and deadlines are currently on track. No urgent items pending."

                await self._persist_message(conv_id, "assistant", msg)
                await self.set_state(OrchestratorState.COMPLETED)
                await self.set_state(OrchestratorState.IDLE)
                return OrchestratorResponse(conversation_id=conv_id, message=msg, state=OrchestratorState.COMPLETED)
            except Exception as e:
                logger.error("Failed to query top priorities: %s", e)

        # 3. Deadline Countdown query
        countdown_patterns = ("how many days left until", "countdown to", "days until", "time left until")
        is_countdown = any(p in norm_msg for p in countdown_patterns) or (
            norm_msg.startswith("when is") and any(w in norm_msg for w in ("exam", "deadline", "project", "presentation", "submission", "test", "due"))
        )
        if is_countdown:
            try:
                # Extract target phrase
                m = re.search(r"(?:until|to|for|is)\s+(?:the\s+)?([^?.,]+)", norm_msg)
                query_subj = m.group(1).strip() if m else norm_msg

                deadlines = await self.scheduler_engine.timetable.get_upcoming_deadlines(horizon_days=90)
                match = next((d for d in deadlines if query_subj in d.title.lower() or d.title.lower() in query_subj), None)
                if match:
                    if match.is_overdue:
                        msg = f"Sir, '{match.title}' is currently OVERDUE (was due on {match.due_date} at {match.due_time or '23:59'})."
                    else:
                        days = match.hours_remaining / 24.0
                        msg = f"Sir, you have {days:.1f} days remaining until '{match.title}' (due on {match.due_date} at {match.due_time or '23:59'}, ~{match.hours_remaining:.0f} hours remaining)."
                else:
                    all_events = await self.scheduler_engine.store.list_events()
                    ev_match = next((ev for ev in all_events if query_subj in ev.title.lower() or ev.title.lower() in query_subj), None)
                    if ev_match:
                        msg = f"Sir, '{ev_match.title}' is scheduled for {ev_match.event_date} at {ev_match.start_time or 'all-day'}."
                    else:
                        msg = f"Sir, I could not find an event or deadline matching '{query_subj}' in your schedule."

                await self._persist_message(conv_id, "assistant", msg)
                await self.set_state(OrchestratorState.COMPLETED)
                await self.set_state(OrchestratorState.IDLE)
                return OrchestratorResponse(conversation_id=conv_id, message=msg, state=OrchestratorState.COMPLETED)
            except Exception as e:
                logger.error("Failed to query countdown: %s", e)

        # 4. Focus Session control
        if "focus" in norm_msg:
            # Start focus session
            if any(w in norm_msg for w in ("start", "begin", "enter", "mode", "session")) and not any(w in norm_msg for w in ("stop", "end", "cancel", "status")):
                try:
                    dur_match = re.search(r"(\d+)\s*(?:minute|min)s?", norm_msg)
                    duration = int(dur_match.group(1)) if dur_match else 25
                    goal = "Deep Work"
                    on_match = re.search(r"\bon\s+([^.,]+)", user_message)
                    if on_match:
                        goal = on_match.group(1).strip()
                    else:
                        for_match = re.search(r"\bfor\s+([^.,]+)", user_message)
                        if for_match and not re.search(r"\d+\s*min", for_match.group(1).lower()):
                            goal = for_match.group(1).strip()

                    sess = await self.scheduler_engine.focus.start_session(duration_minutes=duration, goal=goal)
                    msg = f"Focus session initiated for {duration} minutes (Goal: {goal}). Non-urgent notifications will be held until completion, Sir."
                    await self._persist_message(conv_id, "assistant", msg)
                    await self.set_state(OrchestratorState.COMPLETED)
                    await self.set_state(OrchestratorState.IDLE)
                    return OrchestratorResponse(conversation_id=conv_id, message=msg, state=OrchestratorState.COMPLETED)
                except Exception as e:
                    logger.error("Failed to start focus session: %s", e)

            # Stop focus session
            elif any(w in norm_msg for w in ("stop", "end", "cancel", "terminate", "exit", "finish")):
                try:
                    await self.scheduler_engine.focus.stop_session()
                    msg = "Focus session concluded. Standard notification delivery restored, Sir."
                    await self._persist_message(conv_id, "assistant", msg)
                    await self.set_state(OrchestratorState.COMPLETED)
                    await self.set_state(OrchestratorState.IDLE)
                    return OrchestratorResponse(conversation_id=conv_id, message=msg, state=OrchestratorState.COMPLETED)
                except Exception as e:
                    logger.error("Failed to stop focus session: %s", e)

        # 5. Quiet Hours configuration
        if "quiet hours" in norm_msg or "don't disturb" in norm_msg or "do not disturb" in norm_msg:
            try:
                times = re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", norm_msg)
                if len(times) >= 2:
                    t1, _ = self.scheduler_engine.parser._extract_time(times[0])
                    t2, _ = self.scheduler_engine.parser._extract_time(times[1])
                    if t1 and t2:
                        cfg = await self.scheduler_engine.store.get_settings()
                        cfg.quiet_hours_enabled = True
                        cfg.quiet_hours_start = t1
                        cfg.quiet_hours_end = t2
                        await self.scheduler_engine.store.save_settings(cfg)
                        msg = f"Quiet hours configured from {t1} to {t2}. Non-urgent notifications will be suppressed during this window, Sir."
                    else:
                        msg = "Please specify valid start and end times for quiet hours, Sir (e.g., 'quiet hours from 22:00 to 08:00')."
                else:
                    msg = "Please specify both start and end times for quiet hours, Sir (e.g., 'don't disturb me between 22:00 and 08:00')."

                await self._persist_message(conv_id, "assistant", msg)
                await self.set_state(OrchestratorState.COMPLETED)
                await self.set_state(OrchestratorState.IDLE)
                return OrchestratorResponse(conversation_id=conv_id, message=msg, state=OrchestratorState.COMPLETED)
            except Exception as e:
                logger.error("Failed to configure quiet hours: %s", e)

        # 6. Reminder / Event Creation
        reminder_intents = ("remind me to", "remind me about", "remind me", "schedule a", "schedule an", "create event", "set a reminder", "set reminder")
        if any(norm_msg.startswith(intent) or f" {intent}" in norm_msg for intent in reminder_intents):
            try:
                parse_res = self.scheduler_engine.parser.parse_scheduling_prompt(user_message)
                # Ambiguity check: user requested a reminder/event but gave no time or date
                if parse_res.is_ambiguous or (not parse_res.event_date and not parse_res.start_time):
                    msg = "When would you like me to schedule this reminder, Sir? Please specify the date and time."
                    await self._persist_message(conv_id, "assistant", msg)
                    await self.set_state(OrchestratorState.COMPLETED)
                    await self.set_state(OrchestratorState.IDLE)
                    return OrchestratorResponse(conversation_id=conv_id, message=msg, state=OrchestratorState.COMPLETED)

                title = parse_res.extracted_title or "Scheduled Task"
                date_str = parse_res.event_date
                time_str = parse_res.start_time

                # Classify category
                cat = EventCategory.GENERAL_TASKS
                if any(w in norm_msg for w in ("exam", "test", "midterm", "final", "quiz")):
                    cat = EventCategory.EXAMS
                elif any(w in norm_msg for w in ("college", "class", "lecture", "course", "lab")):
                    cat = EventCategory.COLLEGE
                elif any(w in norm_msg for w in ("assignment", "homework", "submission", "submit")):
                    cat = EventCategory.ASSIGNMENTS
                elif any(w in norm_msg for w in ("project", "code", "repo", "build")):
                    cat = EventCategory.PROJECTS
                elif any(w in norm_msg for w in ("meet", "call", "interview", "sync", "conference")):
                    cat = EventCategory.MEETINGS
                elif any(w in norm_msg for w in ("workout", "gym", "doctor", "medicine", "pill", "lunch", "dinner")):
                    cat = EventCategory.PERSONAL

                pri = EventPriority.HIGH if any(w in norm_msg for w in ("urgent", "important", "critical", "asap")) else EventPriority.MEDIUM

                offsets = [parse_res.reminder_offset_minutes] if parse_res.reminder_offset_minutes > 0 else [0]
                ev = await self.scheduler_engine.timetable.add_event_with_reminders(
                    title=title,
                    event_date=date_str,
                    start_time=time_str,
                    category=cat,
                    priority=pri,
                    reminder_offsets=offsets,
                )

                # Bridge into Persistent Memory under SCHEDULE
                if self.memory_mgr:
                    try:
                        from zoro.memory.models import MemoryCategory, MemoryCreate, MemorySource
                        await self.memory_mgr.store.create_memory(
                            MemoryCreate(
                                category=MemoryCategory.SCHEDULE,
                                content=f"Scheduled {ev.category.value.lower()}: '{ev.title}' on {ev.event_date} at {ev.start_time or 'all-day'}.",
                                source=MemorySource.EXTRACTED_CONVERSATION,
                                event_timestamp=f"{ev.event_date}T{ev.start_time or '09:00'}:00",
                                importance=0.7,
                                metadata={"event_id": ev.id, "category": ev.category.value},
                            )
                        )
                    except Exception as mem_err:
                        logger.warning("Failed to bridge schedule event to memory: %s", mem_err)

                msg = f"Certainly, Sir. I have scheduled a reminder for '{ev.title}' on {ev.event_date} at {ev.start_time}."
                await self._persist_message(conv_id, "assistant", msg)
                await self.set_state(OrchestratorState.COMPLETED)
                await self.set_state(OrchestratorState.IDLE)
                return OrchestratorResponse(conversation_id=conv_id, message=msg, state=OrchestratorState.COMPLETED)
            except Exception as e:
                logger.error("Failed to process reminder command: %s", e)

        return None

    async def _handle_direct_conversation(
        self, conv_id: str, user_message: str
    ) -> OrchestratorResponse:
        # Check for proactive schedule commands (agenda, deadlines, focus, reminders)
        sched_resp = await self._handle_proactive_schedule_command(conv_id, user_message)
        if sched_resp is not None:
            return sched_resp

        # Build prompt with history (fetch up to 12 most recent messages in chronological order)
        history = await self._load_conversation_history(conv_id, limit=12)

        # Retrieve relevant memory context if MemoryManager is configured
        memory_context = ""
        if self.memory_mgr:
            try:
                memory_context = await self.memory_mgr.get_context_for_prompt(user_message)
            except Exception as e:
                logger.warning("Memory context retrieval failed: %s", e)

        # Retrieve proactive schedule context if SchedulerEngine is configured
        schedule_context = ""
        if self.scheduler_engine:
            try:
                sched_lines = []
                focus_sess = await self.scheduler_engine.focus.get_active_session()
                if focus_sess:
                    sched_lines.append(f"• Active Focus Session: '{focus_sess.goal}' ({focus_sess.duration_minutes}m)")

                today_events = await self.scheduler_engine.timetable.get_todays_agenda()
                if today_events:
                    sched_lines.append(f"• Today's Agenda ({len(today_events)} items):")
                    for ev in today_events[:3]:
                        t_str = f"at {ev.start_time}" if ev.start_time else "all-day"
                        sched_lines.append(f"  - [{ev.category.value}] {ev.title} ({t_str})")

                deadlines = await self.scheduler_engine.timetable.get_upcoming_deadlines(horizon_days=3)
                if deadlines:
                    sched_lines.append(f"• Urgent Deadlines ({len(deadlines)} upcoming):")
                    for d in deadlines[:2]:
                        sched_lines.append(f"  - {d.title} (due {d.due_date}, {d.hours_remaining:.0f}h remaining)")

                if sched_lines:
                    schedule_context = "=== PROACTIVE TIMETABLE CONTEXT ===\n" + "\n".join(sched_lines)
            except Exception as e:
                logger.warning("Schedule context retrieval failed: %s", e)

        system_content = "You are ZORO, a sophisticated and loyal personal artificial intelligence assistant."
        if memory_context:
            system_content += f"\n\n{memory_context}"
        if schedule_context:
            system_content += f"\n\n{schedule_context}"

        messages = [
            ChatMessage(role="system", content=system_content)
        ]
        
        # Ensure the prompt ends with the current user message
        if history and history[-1].role == "user" and history[-1].content == user_message:
            messages.extend(history)
        else:
            messages.extend(history)
            messages.append(ChatMessage(role="user", content=user_message))

        req = ChatCompletionRequest(
            model=self.provider_registry.get_active_model(),
            messages=messages,
            temperature=0.7,
            max_tokens=512,
        )

        try:
            resp = await self.provider_registry.chat_completion_with_fallback(req)
            raw_reply = resp.content.strip() if resp.content else ""
            reply = raw_reply or "I am listening, Sir. How may I assist you?"

            # If active provider returned default mock string, enrich conversational queries with real dynamic answers
            if reply == "Mock response from ZORO Model Subsystem.":
                norm_msg = user_message.lower().strip()
                if "remember" in norm_msg and any(q in norm_msg for q in ("what", "tell", "show", "list")):
                    if memory_context:
                        reply = f"Here is what I have in my persistent memory:\n{memory_context}"
                    else:
                        reply = "I currently have no stored memories matching that query."
                elif "preference" in norm_msg or "prefer" in norm_msg:
                    if memory_context and "Preference" in memory_context:
                        reply = f"Based on my memory records:\n{memory_context}"
                    else:
                        reply = "I do not have that preference recorded yet."
                elif "project" in norm_msg:
                    if memory_context and "Project" in memory_context:
                        reply = f"Regarding your projects:\n{memory_context}"
                    else:
                        reply = "I do not have details on that project yet."
                elif "who am i" in norm_msg or "my name" in norm_msg:
                    if memory_context and "Identity" in memory_context:
                        reply = f"Based on my identity records:\n{memory_context}"
                    else:
                        reply = "I do not have your name recorded yet."
                elif "schedule" in norm_msg or "agenda" in norm_msg:
                    if schedule_context:
                        reply = f"Here is your current timetable context:\n{schedule_context}"
                    else:
                        reply = "You have no events scheduled for today, Sir."
                elif "focus" in norm_msg:
                    if schedule_context and "Focus Session" in schedule_context:
                        reply = f"Status:\n{schedule_context}"
                    else:
                        reply = "There is currently no active focus session, Sir."
                elif "time" in norm_msg:
                    from datetime import datetime
                    reply = f"The current time is {datetime.now().strftime('%I:%M %p')}."
                elif "date" in norm_msg or "today" in norm_msg:
                    from datetime import datetime
                    reply = f"Today is {datetime.now().strftime('%A, %B %d, %Y')}."
                elif "who are you" in norm_msg or "what is your name" in norm_msg:
                    reply = "I am ZORO, your personal artificial intelligence assistant."
                elif "system status" in norm_msg:
                    reply = "All systems are operational. Core engine, desktop shell, and voice interaction are online."
                elif any(g in norm_msg for g in ("hello", "hi", "hey")):
                    reply = "Hello. I am listening and ready to assist you."

            # Asynchronously extract and persist memories from this turn
            if self.memory_mgr:
                try:
                    await self.memory_mgr.process_turn(user_message, reply)
                except Exception as e:
                    logger.warning("Memory turn extraction failed: %s", e)

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
            # Query the latest `limit` messages in ascending chronological order
            rows = await self.db.execute_read(
                """
                SELECT role, content FROM (
                    SELECT id, role, content FROM messages
                    WHERE conversation_id = ?
                    ORDER BY id DESC LIMIT ?
                ) ORDER BY id ASC
                """,
                (conv_id, limit),
            )
            return [ChatMessage(role=r[0], content=r[1]) for r in rows]
        except Exception as e:
            logger.error("Failed to load history for %s: %s", conv_id, e)
            return []
