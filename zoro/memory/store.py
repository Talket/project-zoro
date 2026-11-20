"""Persistent SQLite Storage and Hybrid Search for PROJECT ZORO Milestone 05."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import aiosqlite
import numpy as np

from zoro.memory.embeddings import LocalEmbeddingEngine
from zoro.memory.models import (
    EventStatus,
    MemoryCategory,
    MemoryCreate,
    MemoryFilter,
    MemoryItem,
    MemorySource,
    MemoryUpdate,
    SearchResult,
)

logger = logging.getLogger(__name__)


class MemoryStore:
    """
    Manages persistent memory storage in SQLite with hybrid semantic and keyword retrieval.
    """

    def __init__(
        self,
        db_path: str,
        embedding_engine: Optional[LocalEmbeddingEngine] = None,
    ) -> None:
        self.db_path = db_path
        self.embedder = embedding_engine or LocalEmbeddingEngine()

    async def create_memory(self, item: MemoryCreate) -> MemoryItem:
        """Persist a new memory with dense vector embedding."""
        memory_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        # Generate local embedding with provenance tracking
        vector, emb_model = self.embedder.embed_text_with_metadata(item.content)
        embedding_bytes = self.embedder.vector_to_bytes(vector)

        meta = dict(item.metadata or {})
        meta["embedding_model"] = emb_model
        metadata_str = json.dumps(meta)
        event_status_val = item.event_status.value if item.event_status else "PLANNED"

        query = """
        INSERT INTO memories (
            id, category, content, summary, importance, confidence,
            source, project_name, event_timestamp, event_status,
            metadata_json, embedding, created_at, updated_at, is_deleted
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """
        params = (
            memory_id,
            item.category.value,
            item.content,
            item.summary,
            item.importance,
            item.confidence,
            item.source.value,
            item.project_name,
            item.event_timestamp,
            event_status_val,
            metadata_str,
            embedding_bytes,
            now,
            now,
        )

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute("PRAGMA foreign_keys = ON;")
            await conn.execute(query, params)
            await conn.commit()

        logger.info("Created persistent memory [%s] ID: %s (Source: %s)", item.category.value, memory_id, item.source.value)
        return MemoryItem(
            id=memory_id,
            category=item.category,
            content=item.content,
            summary=item.summary,
            importance=item.importance,
            confidence=item.confidence,
            source=item.source,
            project_name=item.project_name,
            event_timestamp=item.event_timestamp,
            event_status=item.event_status,
            metadata=meta,
            created_at=now,
            updated_at=now,
            is_deleted=False,
        )

    create = create_memory

    async def get_memory(self, memory_id: str, include_deleted: bool = False) -> Optional[MemoryItem]:
        """Retrieve a single memory by ID."""
        query = "SELECT * FROM memories WHERE id = ?"
        if not include_deleted:
            query += " AND is_deleted = 0"

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, (memory_id,))
            row = await cursor.fetchone()
            if not row:
                return None
            return self._row_to_item(row)

    async def update_memory(self, memory_id: str, updates: MemoryUpdate) -> Optional[MemoryItem]:
        """Update an existing memory item, recalculating embeddings if content changes."""
        existing = await self.get_memory(memory_id, include_deleted=True)
        if not existing:
            logger.warning("Attempted to update nonexistent memory ID: %s", memory_id)
            return None

        now = datetime.now(timezone.utc).isoformat()
        fields: List[str] = ["updated_at = ?"]
        params: List[Any] = [now]

        new_content = updates.content if updates.content is not None else existing.content
        if updates.content is not None:
            fields.append("content = ?")
            params.append(updates.content)
            # Recompute embedding
            new_vector = self.embedder.embed_text(updates.content)
            fields.append("embedding = ?")
            params.append(self.embedder.vector_to_bytes(new_vector))

        if updates.summary is not None:
            fields.append("summary = ?")
            params.append(updates.summary)

        if updates.importance is not None:
            fields.append("importance = ?")
            params.append(updates.importance)

        if updates.confidence is not None:
            fields.append("confidence = ?")
            params.append(updates.confidence)

        if updates.project_name is not None:
            fields.append("project_name = ?")
            params.append(updates.project_name)

        if updates.event_timestamp is not None:
            fields.append("event_timestamp = ?")
            params.append(updates.event_timestamp)

        if updates.event_status is not None:
            fields.append("event_status = ?")
            params.append(updates.event_status.value)

        if updates.metadata is not None:
            merged_meta = {**existing.metadata, **updates.metadata}
            fields.append("metadata_json = ?")
            params.append(json.dumps(merged_meta))

        if updates.source is not None:
            fields.append("source = ?")
            params.append(updates.source.value)

        params.append(memory_id)
        query = f"UPDATE memories SET {', '.join(fields)} WHERE id = ?"

        async with aiosqlite.connect(self.db_path) as conn:
            await conn.execute(query, tuple(params))
            await conn.commit()

        logger.info("Updated memory ID: %s", memory_id)
        return await self.get_memory(memory_id, include_deleted=True)

    async def delete_memory(self, memory_id: str, hard_delete: bool = False) -> bool:
        """Delete a memory item (soft delete by default for recovery safety)."""
        async with aiosqlite.connect(self.db_path) as conn:
            if hard_delete:
                cursor = await conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            else:
                now = datetime.now(timezone.utc).isoformat()
                cursor = await conn.execute(
                    "UPDATE memories SET is_deleted = 1, updated_at = ? WHERE id = ? AND is_deleted = 0",
                    (now, memory_id),
                )
            await conn.commit()
            deleted = cursor.rowcount > 0

        if deleted:
            logger.info("Deleted memory ID %s (hard=%s)", memory_id, hard_delete)
        return deleted

    async def delete_by_category(self, category: MemoryCategory, hard_delete: bool = False) -> int:
        """Delete all memories in a given category."""
        async with aiosqlite.connect(self.db_path) as conn:
            if hard_delete:
                cursor = await conn.execute("DELETE FROM memories WHERE category = ?", (category.value,))
            else:
                now = datetime.now(timezone.utc).isoformat()
                cursor = await conn.execute(
                    "UPDATE memories SET is_deleted = 1, updated_at = ? WHERE category = ? AND is_deleted = 0",
                    (now, category.value),
                )
            await conn.commit()
            count = cursor.rowcount

        logger.info("Deleted %d memories in category %s (hard=%s)", count, category.value, hard_delete)
        return count

    async def clear_all_memories(self, confirmation_phrase: str, hard_delete: bool = False) -> int:
        """
        Clear all personal memories with explicit confirmation requirement.
        Security Guard: requires confirmation_phrase == 'CONFIRM_CLEAR_ALL_MEMORIES'.
        """
        if confirmation_phrase != "CONFIRM_CLEAR_ALL_MEMORIES":
            raise ValueError(
                "Security guard rejected clear_all_memories: Invalid confirmation phrase! "
                "Must be exactly 'CONFIRM_CLEAR_ALL_MEMORIES'."
            )

        async with aiosqlite.connect(self.db_path) as conn:
            if hard_delete:
                cursor = await conn.execute("DELETE FROM memories")
            else:
                now = datetime.now(timezone.utc).isoformat()
                cursor = await conn.execute(
                    "UPDATE memories SET is_deleted = 1, updated_at = ? WHERE is_deleted = 0",
                    (now,),
                )
            await conn.commit()
            count = cursor.rowcount

        logger.warning("CLEARED ALL MEMORIES! Total affected: %d (hard=%s)", count, hard_delete)
        return count

    async def get_all(self, filter_criteria: Optional[MemoryFilter] = None) -> List[MemoryItem]:
        """Query memories matching filter criteria."""
        filt = filter_criteria or MemoryFilter()
        clauses = []
        params = []

        if not filt.include_deleted:
            clauses.append("is_deleted = 0")

        if filt.category:
            clauses.append("category = ?")
            params.append(filt.category.value)

        if filt.project_name:
            clauses.append("project_name = ?")
            params.append(filt.project_name)

        if filt.source:
            clauses.append("source = ?")
            params.append(filt.source.value)

        if filt.event_status:
            clauses.append("event_status = ?")
            params.append(filt.event_status.value)

        where_stmt = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = f"""
        SELECT * FROM memories
        {where_stmt}
        ORDER BY importance DESC, created_at DESC
        LIMIT ? OFFSET ?
        """
        params.extend([filt.limit, filt.offset])

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query, tuple(params))
            rows = await cursor.fetchall()
            return [self._row_to_item(row) for row in rows]

    async def search(
        self,
        query: str,
        category: Optional[MemoryCategory] = None,
        project_name: Optional[str] = None,
        limit: int = 10,
        min_score: float = 0.25,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3,
    ) -> List[SearchResult]:
        """
        Execute hybrid search combining dense vector cosine similarity and FTS5 keyword matching.
        """
        cleaned_query = query.strip()
        if not cleaned_query:
            return []

        # 1. Fetch keyword matches via FTS5
        fts_scores: Dict[str, float] = {}
        try:
            # Sanitize query for FTS5 using OR for broad hybrid keyword recall
            tokens = [w for w in cleaned_query.split() if w.isalnum() and len(w) > 1]
            fts_term = " OR ".join(tokens) if tokens else ""
            if fts_term:
                async with aiosqlite.connect(self.db_path) as conn:
                    fts_sql = """
                    SELECT id, rank FROM memories_fts
                    WHERE memories_fts MATCH ?
                    ORDER BY rank
                    LIMIT 50
                    """
                    cursor = await conn.execute(fts_sql, (fts_term,))
                    rows = await cursor.fetchall()
                    for mem_id, rank in rows:
                        # SQLite FTS5 rank is negative (lower = better), normalize to [0, 1]
                        norm_rank = max(0.0, min(1.0, 1.0 / (1.0 + abs(float(rank)))))
                        fts_scores[mem_id] = norm_rank
        except Exception as e:
            logger.debug("FTS5 keyword search query failed: %s", e)

        # 2. Dense semantic search with space compatibility guard
        query_vector, query_model = self.embedder.embed_text_with_metadata(cleaned_query)

        # Retrieve active candidates
        where_clauses = ["is_deleted = 0"]
        params: List[Any] = []
        if category:
            where_clauses.append("category = ?")
            params.append(category.value)
        if project_name:
            where_clauses.append("project_name = ?")
            params.append(project_name)

        query_sql = f"""
        SELECT * FROM memories
        WHERE {' AND '.join(where_clauses)}
        """

        candidates: List[Tuple[MemoryItem, float, str]] = []
        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(query_sql, tuple(params))
            rows = await cursor.fetchall()

            for row in rows:
                item = self._row_to_item(row)
                embedding_blob = row["embedding"]

                sem_score = 0.0
                mem_model = item.metadata.get("embedding_model") if item.metadata else None

                # Invariant: Never compare vectors from differing embedding spaces (e.g. all-minilm vs fallback-ngram)
                is_compatible_space = (
                    mem_model is None  # Legacy entries assume default model
                    or query_model == mem_model
                    or query_model == "none"
                )

                if embedding_blob and is_compatible_space:
                    mem_vector = self.embedder.bytes_to_vector(embedding_blob)
                    sem_score = max(0.0, self.embedder.cosine_similarity(query_vector, mem_vector))
                elif embedding_blob and not is_compatible_space:
                    logger.debug(
                        "Skipping vector similarity for memory '%s': incompatible spaces (%s vs %s)",
                        item.id,
                        query_model,
                        mem_model,
                    )

                kw_score = fts_scores.get(item.id, 0.0)

                # Combined hybrid score with importance weighting
                hybrid_score = (sem_score * semantic_weight) + (kw_score * keyword_weight)
                # Modulate slightly by memory importance
                final_score = hybrid_score * (0.85 + 0.15 * item.importance)

                if final_score >= min_score:
                    match_type = "hybrid" if (sem_score > 0.3 and kw_score > 0.1) else (
                        "keyword" if kw_score > sem_score else "semantic"
                    )
                    candidates.append((item, final_score, match_type))

        # Sort descending by score
        candidates.sort(key=lambda x: x[1], reverse=True)
        top_candidates = candidates[:limit]

        return [
            SearchResult(memory=item, score=round(score, 4), match_type=mtype)
            for item, score, mtype in top_candidates
        ]

    async def find_similar_memory(
        self,
        content: str,
        category: MemoryCategory,
        threshold: float = 0.70,
        project_name: Optional[str] = None,
    ) -> Optional[Tuple[MemoryItem, float]]:
        """
        Check if a highly similar memory already exists in this category.
        Used for duplicate and contradiction detection.
        """
        results = await self.search(
            query=content,
            category=category,
            project_name=project_name,
            limit=1,
            min_score=threshold,
            semantic_weight=0.9,
            keyword_weight=0.1,
        )
        if results:
            return results[0].memory, results[0].score
        return None

    def _row_to_item(self, row: Any) -> MemoryItem:
        """Convert a SQLite row to a MemoryItem domain instance."""
        meta_raw = row["metadata_json"]
        meta_dict = json.loads(meta_raw) if meta_raw else {}

        ev_status = None
        if row["event_status"]:
            try:
                ev_status = EventStatus(row["event_status"])
            except ValueError:
                pass

        return MemoryItem(
            id=row["id"],
            category=MemoryCategory(row["category"]),
            content=row["content"],
            summary=row["summary"],
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            source=MemorySource(row["source"]),
            project_name=row["project_name"],
            event_timestamp=row["event_timestamp"],
            event_status=ev_status,
            metadata=meta_dict,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_deleted=bool(row["is_deleted"]),
        )
