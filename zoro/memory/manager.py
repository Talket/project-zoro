"""Central Facade Orchestrating Multi-Tiered Personal Memory for PROJECT ZORO."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from zoro.memory.context_builder import MemoryContextBuilder
from zoro.memory.embeddings import LocalEmbeddingEngine
from zoro.memory.extractor import ExtractedMemoryCandidate, MemoryExtractor
from zoro.memory.models import (
    MemoryCategory,
    MemoryFilter,
    MemoryItem,
    MemorySource,
    MemoryUpdate,
    SearchResult,
)
from zoro.memory.store import MemoryStore

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Main entry point for Project ZORO's persistent personal memory architecture.
    Coordinates Store, LocalEmbeddingEngine, Extractor, and ContextBuilder.
    """

    def __init__(
        self,
        db_path: str,
        embedding_engine: Optional[LocalEmbeddingEngine] = None,
        context_budget_tokens: int = 600,
    ) -> None:
        self.db_path = db_path
        self.embedder = embedding_engine or LocalEmbeddingEngine()
        self.store = MemoryStore(db_path=db_path, embedding_engine=self.embedder)
        self.extractor = MemoryExtractor()
        self.context_builder = MemoryContextBuilder(max_tokens=context_budget_tokens)

    async def get_context_for_prompt(self, prompt: str) -> str:
        """
        Retrieve relevant personal memories and format into a grounded prompt section.
        Combines top semantic matches with permanent Identity memories.
        """
        cleaned = prompt.strip()
        if not cleaned:
            return ""

        # 1. Fetch relevant memories via hybrid search
        search_results = await self.store.search(
            query=cleaned,
            limit=6,
            min_score=0.25,
            semantic_weight=0.75,
            keyword_weight=0.25,
        )

        # 2. Fetch baseline Identity memories (e.g. user name and profession)
        identity_items = await self.store.get_all(
            MemoryFilter(category=MemoryCategory.IDENTITY, limit=3)
        )
        identity_results = [
            SearchResult(memory=m, score=1.0, match_type="identity_baseline")
            for m in identity_items
        ]

        # 3. Assemble and budget into prompt block
        return self.context_builder.build_memory_context(
            search_results=search_results,
            identity_memories=identity_results,
        )

    async def process_turn(
        self,
        user_message: str,
        assistant_reply: Optional[str] = None,
    ) -> List[MemoryItem]:
        """
        Analyze completed conversation turn, handle explicit commands or extract new facts,
        resolve contradictions/duplicates, and persist memories.
        """
        candidates = self.extractor.extract_from_utterance(user_message, assistant_reply)
        if not candidates:
            return []

        saved_memories: List[MemoryItem] = []

        for candidate in candidates:
            # Handle explicit commands
            if candidate.is_explicit_command:
                item = await self._handle_explicit_command(candidate)
                if item:
                    saved_memories.append(item)
                continue

            # Standard extracted candidate: check for duplicate or contradiction
            item = await self._persist_with_deduplication(candidate)
            if item:
                saved_memories.append(item)

        return saved_memories

    async def _handle_explicit_command(
        self,
        candidate: ExtractedMemoryCandidate,
    ) -> Optional[MemoryItem]:
        """Handle explicit 'remember', 'update', or 'forget' instructions."""
        action = candidate.command_action

        if action == "forget":
            # Find closest matching memory in candidate category, or across all categories
            match = await self.store.find_similar_memory(
                content=candidate.content,
                category=candidate.category,
                threshold=0.35,
            )
            if not match:
                # Fallback: search across all categories without category filter
                results = await self.store.search(
                    query=candidate.content,
                    category=None,
                    limit=1,
                    min_score=0.25,
                )
                if results:
                    match = (results[0].memory, results[0].score)

            if match:
                existing_mem, score = match
                logger.info("Executing explicit forget for memory ID %s (Score: %.2f)", existing_mem.id, score)
                await self.store.delete_memory(existing_mem.id, hard_delete=False)
                existing_mem.is_deleted = True
                return existing_mem
            else:
                logger.info("Explicit forget: No matching memory found for '%.40s'", candidate.content)
                return None

        elif action == "update":
            # Find existing memory to update
            match = await self.store.find_similar_memory(
                content=candidate.content,
                category=candidate.category,
                threshold=0.40,
            )
            if match:
                existing_mem, score = match
                logger.info("Updating existing memory ID %s with new preference", existing_mem.id)
                updated = await self.store.update_memory(
                    existing_mem.id,
                    MemoryUpdate(
                        content=candidate.content,
                        summary=candidate.summary,
                        importance=candidate.importance,
                        confidence=candidate.confidence,
                        source=MemorySource.EXPLICIT_USER,
                    ),
                )
                return updated
            else:
                # No existing memory found: create new
                return await self.store.create_memory(candidate.to_create_model())

        else:  # "remember"
            # Explicit remember: check if identical already exists
            match = await self.store.find_similar_memory(
                content=candidate.content,
                category=candidate.category,
                threshold=0.85,
            )
            if match:
                existing_mem, score = match
                logger.info("Explicit remember: identical memory already exists (ID: %s, Score: %.2f)", existing_mem.id, score)
                return existing_mem

            return await self.store.create_memory(candidate.to_create_model())

    async def _persist_with_deduplication(
        self,
        candidate: ExtractedMemoryCandidate,
    ) -> Optional[MemoryItem]:
        """
        Persist extracted memory candidate while preventing duplicate or contradictory entries.
        """
        # For PREFERENCE and IDENTITY: check for similar existing record to update
        if candidate.category in (MemoryCategory.PREFERENCE, MemoryCategory.IDENTITY):
            match = await self.store.find_similar_memory(
                content=candidate.content,
                category=candidate.category,
                threshold=0.60,
                project_name=candidate.project_name,
            )
            if match:
                existing_mem, score = match
                # Update existing memory with the newer information
                logger.info(
                    "Updating existing [%s] memory ID %s (Score: %.2f) to resolve contradiction/update",
                    candidate.category.value,
                    existing_mem.id,
                    score,
                )
                return await self.store.update_memory(
                    existing_mem.id,
                    MemoryUpdate(
                        content=candidate.content,
                        summary=candidate.summary,
                        importance=candidate.importance,
                        confidence=candidate.confidence,
                        source=candidate.source,
                    ),
                )

        # For PROJECT, EPISODIC, SCHEDULE: if very high semantic match (>0.85), avoid duplicate
        match = await self.store.find_similar_memory(
            content=candidate.content,
            category=candidate.category,
            threshold=0.85,
            project_name=candidate.project_name,
        )
        if match:
            existing_mem, score = match
            logger.debug("Skipping duplicate memory for [%s] (Score: %.2f)", candidate.category.value, score)
            return existing_mem

        return await self.store.create_memory(candidate.to_create_model())
