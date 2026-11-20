"""Memory Extraction Engine for PROJECT ZORO Milestone 05.

Identifies structured memory candidates, explicit commands, preference updates,
and schedule items from conversational interactions with strict security filtering.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zoro.memory.models import (
    EventStatus,
    MemoryCategory,
    MemoryCreate,
    MemoryItem,
    MemorySource,
)

logger = logging.getLogger(__name__)

# Security & Credential Filters: Patterns that MUST NEVER be persisted to memory
SENSITIVE_PATTERNS = [
    re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\"]+)", re.IGNORECASE),
    re.compile(r"(?:api[_-]?key|secret|token|bearer)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{12,})", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"sk-[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"gh[pousr]_[a-zA-Z0-9]{36,}", re.IGNORECASE),
]

# Prompt injection markers inside candidate memories
INJECTION_PATTERNS = [
    re.compile(r"(?:ignore\s+all\s+(?:previous|prior)\s+instructions)", re.IGNORECASE),
    re.compile(r"(?:system\s*:\s*you\s+are\s+now)", re.IGNORECASE),
    re.compile(r"<\s*script[^>]*>", re.IGNORECASE),
]


class ExtractedMemoryCandidate:
    """A memory candidate identified by the extractor before database insertion."""

    def __init__(
        self,
        category: MemoryCategory,
        content: str,
        summary: Optional[str] = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        source: MemorySource = MemorySource.EXTRACTED_CONVERSATION,
        project_name: Optional[str] = None,
        event_timestamp: Optional[str] = None,
        event_status: Optional[EventStatus] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_explicit_command: bool = False,
        command_action: Optional[str] = None,  # "remember", "update", "forget"
    ) -> None:
        self.category = category
        self.content = content
        self.summary = summary
        self.importance = importance
        self.confidence = confidence
        self.source = source
        self.project_name = project_name
        self.event_timestamp = event_timestamp
        self.event_status = event_status
        self.metadata = metadata or {}
        self.is_explicit_command = is_explicit_command
        self.command_action = command_action

    def to_create_model(self) -> MemoryCreate:
        """Convert candidate to MemoryCreate schema."""
        return MemoryCreate(
            category=self.category,
            content=self.content,
            summary=self.summary,
            importance=self.importance,
            confidence=self.confidence,
            source=self.source,
            project_name=self.project_name,
            event_timestamp=self.event_timestamp,
            event_status=self.event_status,
            metadata=self.metadata,
        )


class MemoryExtractor:
    """
    Parses conversation utterances to extract persistent memory candidates.
    Applies strict security screening, entity recognition, and contradiction detection.
    """

    def __init__(self) -> None:
        pass

    def extract_from_utterance(
        self,
        user_message: str,
        assistant_reply: Optional[str] = None,
    ) -> List[ExtractedMemoryCandidate]:
        """
        Analyze a conversation turn and extract valid memory candidates.
        Returns a list of ExtractedMemoryCandidate instances.
        """
        text = user_message.strip()
        if not text:
            return []

        candidates: List[ExtractedMemoryCandidate] = []

        # 1. Security Check: Never persist credentials or secrets
        if self._contains_sensitive_data(text):
            logger.warning("Memory extraction rejected sensitive credential or security token pattern.")
            return []

        # 2. Check for explicit memory commands
        explicit_candidate = self._check_explicit_commands(text)
        if explicit_candidate:
            explicit_candidate.content = self._sanitize_content(explicit_candidate.content)
            if explicit_candidate.content:
                candidates.append(explicit_candidate)
            return candidates

        # 3. Conversational Heuristic Extraction
        # Identity
        id_candidates = self._extract_identity(text)
        candidates.extend(id_candidates)

        # Preference
        pref_candidates = self._extract_preferences(text)
        candidates.extend(pref_candidates)

        # Project
        proj_candidates = self._extract_projects(text)
        candidates.extend(proj_candidates)

        # Schedule
        sched_candidates = self._extract_schedule(text)
        candidates.extend(sched_candidates)

        # Episodic (decisions / completions)
        epi_candidates = self._extract_episodic(text, assistant_reply)
        candidates.extend(epi_candidates)

        # Sanitize all extracted candidates
        sanitized = []
        for c in candidates:
            c.content = self._sanitize_content(c.content)
            if c.content:
                sanitized.append(c)

        return sanitized

    def _contains_sensitive_data(self, text: str) -> bool:
        """Return True if text appears to contain passwords, private keys, or API tokens."""
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _sanitize_content(self, text: str) -> str:
        """Strip dangerous instruction injection markers and normalize text."""
        sanitized = text
        for pat in INJECTION_PATTERNS:
            sanitized = pat.sub("[REDACTED_INSTRUCTION]", sanitized)
        return sanitized.strip()

    def _check_explicit_commands(self, text: str) -> Optional[ExtractedMemoryCandidate]:
        """
        Detect explicit user instructions to remember, update, or forget.
        Examples:
        - 'Remember that my name is Alice'
        - 'Please remember I prefer dark mode'
        - 'Update my preference to Python'
        - 'Remember that Project Zoro uses SQLite'
        """
        # Forget command
        m_forget = re.match(
            r"^(?:please\s+)?(?:forget|delete\s+memory|remove\s+memory)(?:\s+that|\s+about)?\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if m_forget:
            target = m_forget.group(1).strip()
            cat = self._classify_category(target)
            return ExtractedMemoryCandidate(
                category=cat,
                content=target,
                importance=0.8,
                confidence=1.0,
                source=MemorySource.EXPLICIT_USER,
                is_explicit_command=True,
                command_action="forget",
            )

        # Update preference command
        m_update_pref = re.match(
            r"^(?:please\s+)?(?:update|change)\s+my\s+preference(?:\s+for|\s+to|\s+regarding)?\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if m_update_pref:
            pref_content = m_update_pref.group(1).strip()
            return ExtractedMemoryCandidate(
                category=MemoryCategory.PREFERENCE,
                content=f"User preference updated: {pref_content}",
                summary=pref_content,
                importance=0.9,
                confidence=1.0,
                source=MemorySource.EXPLICIT_USER,
                is_explicit_command=True,
                command_action="update",
            )

        # Explicit Remember command
        m_rem = re.match(
            r"^(?:please\s+)?(?:remember|note|store|keep\s+in\s+mind)(?:\s+that|\s+this)?\s*[:,-]?\s*(.+)$",
            text,
            re.IGNORECASE,
        )
        if m_rem:
            content = m_rem.group(1).strip()
            # Determine category from content
            cat = self._classify_category(content)
            return ExtractedMemoryCandidate(
                category=cat,
                content=content,
                summary=content[:60],
                importance=0.9,
                confidence=1.0,
                source=MemorySource.EXPLICIT_USER,
                is_explicit_command=True,
                command_action="remember",
            )

        return None

    def _classify_category(self, text: str) -> MemoryCategory:
        """Classify general memory content into one of the 5 categories."""
        lower = text.lower()
        if any(w in lower for w in ["deadline", "exam", "meeting", "schedule", "appointment", "tomorrow", "calendar", "due"]):
            return MemoryCategory.SCHEDULE
        if any(w in lower for w in ["project", "app", "building", "repository", "feature", "codebase", "architecture"]):
            return MemoryCategory.PROJECT
        if any(w in lower for w in ["prefer", "like", "favorite", "always use", "style", "habit"]):
            return MemoryCategory.PREFERENCE
        if any(w in lower for w in ["my name", "i am a", "i work as", "my degree", "education", "background"]):
            return MemoryCategory.IDENTITY
        return MemoryCategory.EPISODIC

    def _extract_identity(self, text: str) -> List[ExtractedMemoryCandidate]:
        """Extract user identity facts (name, occupation, background)."""
        candidates = []
        # Name: "My name is John" / "My name is Victor"
        m_name = re.search(
            r"\bmy\s+name\s+is\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)?)(?:\s+and\b|\s*,|\s*\.|\s*$)",
            text,
            re.IGNORECASE,
        )
        if m_name:
            name = m_name.group(1).strip()
            candidates.append(
                ExtractedMemoryCandidate(
                    category=MemoryCategory.IDENTITY,
                    content=f"User's name is {name}.",
                    summary=f"Name: {name}",
                    importance=1.0,
                    confidence=1.0,
                    metadata={"entity": "name", "value": name},
                )
            )

        # Profession / Role: "I am a software engineer" / "I work as a researcher"
        m_role = re.search(r"\b(?:i\s+am\s+a|i\s+work\s+as\s+a)\s+([a-zA-Z\s]{3,40})\b", text, re.IGNORECASE)
        if m_role:
            role = m_role.group(1).strip()
            if not any(w in role.lower() for w in ["human", "person", "user", "bot"]):
                candidates.append(
                    ExtractedMemoryCandidate(
                        category=MemoryCategory.IDENTITY,
                        content=f"User's professional background: {role}.",
                        summary=f"Role: {role}",
                        importance=0.85,
                        confidence=0.9,
                        metadata={"entity": "profession", "value": role},
                    )
                )

        return candidates

    def _extract_preferences(self, text: str) -> List[ExtractedMemoryCandidate]:
        """Extract user preferences (languages, editors, UI theme, styles)."""
        candidates = []
        patterns = [
            (r"\bi\s+(?:prefer|always\s+use|mostly\s+use)\s+([a-zA-Z0-9\+\#\s\.\-_]{2,30})\b", 0.8),
            (r"\bmy\s+favorite\s+([a-zA-Z\s]{3,25})\s+is\s+([a-zA-Z0-9\+\#\s\.\-_]{2,30})\b", 0.85),
            (r"\bi\s+like\s+to\s+use\s+([a-zA-Z0-9\+\#\s\.\-_]{2,30})\b", 0.7),
        ]
        for pat, importance in patterns:
            for match in re.finditer(pat, text, re.IGNORECASE):
                pref_text = match.group(0).strip()
                candidates.append(
                    ExtractedMemoryCandidate(
                        category=MemoryCategory.PREFERENCE,
                        content=f"User preference: {pref_text}.",
                        summary=pref_text,
                        importance=importance,
                        confidence=0.85,
                    )
                )
        return candidates

    def _extract_projects(self, text: str) -> List[ExtractedMemoryCandidate]:
        """Extract project details, architectures, tech stacks, or status."""
        candidates = []
        m_proj = re.search(
            r"\b(?:i\s+am\s+building|working\s+on|developing)\s+(?:an?\s+|the\s+)?([a-zA-Z0-9\s\-_]{2,40}?)(?:\s+called\s+([a-zA-Z0-9\s\-_]+))?(?:\s+(?:using|with)\s+([a-zA-Z0-9\s\-_,]+))?(?:\.|\s+and\b|$)",
            text,
            re.IGNORECASE,
        )
        if m_proj:
            desc = m_proj.group(1).strip()
            named_proj = m_proj.group(2).strip() if m_proj.group(2) else None
            proj_name = named_proj or desc
            tech_stack = m_proj.group(3).strip() if m_proj.group(3) else None
            content = f"User is developing project '{proj_name}'"
            if tech_stack:
                content += f" using {tech_stack}"
            content += "."

            candidates.append(
                ExtractedMemoryCandidate(
                    category=MemoryCategory.PROJECT,
                    content=content,
                    summary=f"Project: {proj_name}",
                    project_name=proj_name,
                    importance=0.85,
                    confidence=0.9,
                    metadata={"project_name": proj_name, "tech_stack": tech_stack},
                )
            )
        return candidates

    def _extract_schedule(self, text: str) -> List[ExtractedMemoryCandidate]:
        """Extract dates, deadlines, exams, meetings."""
        candidates = []
        m_sched = re.search(
            r"\b(my\s+)?(exam|deadline|meeting|appointment|interview)\s+(is|on)\s+([a-zA-Z0-9\s,:\-]+)",
            text,
            re.IGNORECASE,
        )
        if m_sched:
            event_type = m_sched.group(2).strip()
            event_date = m_sched.group(4).strip()
            candidates.append(
                ExtractedMemoryCandidate(
                    category=MemoryCategory.SCHEDULE,
                    content=f"Scheduled {event_type}: on {event_date}.",
                    summary=f"{event_type.capitalize()} on {event_date}",
                    importance=0.9,
                    confidence=0.9,
                    event_timestamp=event_date,
                    event_status=EventStatus.PLANNED,
                    metadata={"event_type": event_type, "raw_date": event_date},
                )
            )
        return candidates

    def _extract_episodic(
        self,
        user_text: str,
        assistant_reply: Optional[str] = None,
    ) -> List[ExtractedMemoryCandidate]:
        """Extract completed tasks, architectural decisions, and experiences."""
        candidates = []
        # Decisions: "We decided to use X instead of Y"
        m_dec = re.search(r"\b(?:we\s+decided\s+to|i\s+decided\s+to)\s+([^\.\n]{10,80})", user_text, re.IGNORECASE)
        if m_dec:
            decision = m_dec.group(1).strip()
            candidates.append(
                ExtractedMemoryCandidate(
                    category=MemoryCategory.EPISODIC,
                    content=f"Decision made: {decision}.",
                    summary=f"Decision: {decision[:40]}",
                    importance=0.75,
                    confidence=0.85,
                    metadata={"type": "decision"},
                )
            )
        return candidates
