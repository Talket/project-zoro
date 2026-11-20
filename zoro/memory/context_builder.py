"""Context-Aware Memory Retrieval and Prompt Grounding for PROJECT ZORO Milestone 05."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from zoro.memory.models import MemoryCategory, SearchResult

logger = logging.getLogger(__name__)

DEFAULT_MAX_MEMORY_TOKENS: int = 600
CHARS_PER_TOKEN: float = 4.0


class MemoryContextBuilder:
    """
    Ranks, formats, and budgets retrieved personal memories into a secure prompt block.
    """

    def __init__(self, max_tokens: int = DEFAULT_MAX_MEMORY_TOKENS) -> None:
        self.max_tokens = max_tokens

    def build_memory_context(
        self,
        search_results: List[SearchResult],
        identity_memories: Optional[List[SearchResult]] = None,
    ) -> str:
        """
        Assemble top relevant memories into a structured prompt injection section.
        Enforces token budget and avoids duplicate memories.
        """
        seen_ids = set()
        categorized: Dict[MemoryCategory, List[str]] = {
            MemoryCategory.IDENTITY: [],
            MemoryCategory.PREFERENCE: [],
            MemoryCategory.PROJECT: [],
            MemoryCategory.SCHEDULE: [],
            MemoryCategory.EPISODIC: [],
        }

        # 1. Always include baseline Identity memories if present
        if identity_memories:
            for res in identity_memories:
                mem = res.memory
                if mem.id not in seen_ids and not mem.is_deleted:
                    seen_ids.add(mem.id)
                    categorized[MemoryCategory.IDENTITY].append(mem.content)

        # 2. Add search results ranked by relevance
        for res in search_results:
            mem = res.memory
            if mem.id not in seen_ids and not mem.is_deleted:
                seen_ids.add(mem.id)
                categorized[mem.category].append(mem.content)

        # Check if any memory exists
        total_items = sum(len(items) for items in categorized.values())
        if total_items == 0:
            return ""

        # 3. Format into structured categories with token budget enforcement
        max_chars = int(self.max_tokens * CHARS_PER_TOKEN)
        lines: List[str] = [
            "<PERSISTENT_MEMORY>",
            "# Verified Personal Memories Profile of the Owner",
            "CRITICAL CONTEXT: The person speaking to you is your owner/user whose profile is below.",
            "You are ZORO, the assistant. Use these verified memories accurately when answering questions about the user.",
        ]

        current_chars = sum(len(l) for l in lines)

        category_labels = [
            (MemoryCategory.IDENTITY, "Identity & Background"),
            (MemoryCategory.PREFERENCE, "Preferences & Working Style"),
            (MemoryCategory.PROJECT, "Current Projects & Architecture"),
            (MemoryCategory.SCHEDULE, "Upcoming Schedules & Deadlines"),
            (MemoryCategory.EPISODIC, "Past Experiences & Decisions"),
        ]

        for cat, label in category_labels:
            items = categorized.get(cat, [])
            if not items:
                continue

            section_header = f"\n[{label}]"
            if current_chars + len(section_header) > max_chars:
                break
            lines.append(section_header)
            current_chars += len(section_header)

            for item_text in items:
                bullet = f"- {item_text}"
                if current_chars + len(bullet) + 1 > max_chars:
                    logger.debug("Memory context budget reached (%d chars). Truncating further items.", current_chars)
                    break
                lines.append(bullet)
                current_chars += len(bullet) + 1

        lines.append("</PERSISTENT_MEMORY>\n")
        return "\n".join(lines)
