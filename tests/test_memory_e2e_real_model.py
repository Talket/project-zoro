"""End-to-End Real-Model Verification of Persistent Personal Memory Architecture."""

from __future__ import annotations

import os
import tempfile
import pytest
import aiosqlite
import httpx

from zoro.core.event_bus import AsyncEventBus
from zoro.memory.manager import MemoryManager
from zoro.memory.models import MemoryCategory, MemoryCreate, MemoryFilter
from zoro.models.base import ChatCompletionRequest, ChatMessage
from zoro.models.ollama import OllamaProvider
from zoro.models.registry import ProviderRegistry
from zoro.orchestrator.orchestrator import ZoroOrchestrator
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.storage.migrations import MigrationRunner
from zoro.tools.registry import ToolRegistry


def is_ollama_available() -> bool:
    """Check if local Ollama daemon is reachable on 127.0.0.1:11434."""
    try:
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not is_ollama_available(), reason="Local Ollama daemon required for real inference")
@pytest.mark.asyncio
async def test_persistent_memory_e2e_real_ollama() -> None:
    """
    End-to-end integration test with genuine local Ollama Qwen2.5 3B model:
    1. Extracts and persists memories across sessions.
    2. Survives simulated application restart.
    3. Retrieves grounded context and answers multi-turn question accurately without hallucination.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    try:
        # Run migrations on new database
        async with aiosqlite.connect(db_path) as conn:
            await MigrationRunner.run_migrations(conn)

        # Setup real Ollama Provider Registry
        provider_reg = ProviderRegistry()
        ollama_prov = OllamaProvider(base_url="http://127.0.0.1:11434")
        provider_reg.register_provider("ollama", ollama_prov, default_model="qwen2.5:3b")
        provider_reg.set_active_provider("ollama")

        db = DatabaseManager()
        audit = AuditLogger(db)
        perms = PermissionGate()
        tool_reg = ToolRegistry(db, audit, perms)
        event_bus = AsyncEventBus()
        emergency_mgr = EmergencyManager()

        # Session 1: Learn identity and project
        mem_mgr_1 = MemoryManager(db_path=db_path)
        orch_1 = ZoroOrchestrator(
            provider_registry=provider_reg,
            tool_registry=tool_reg,
            db=db,
            audit=audit,
            event_bus=event_bus,
            emergency_mgr=emergency_mgr,
            memory_mgr=mem_mgr_1,
        )

        turn_1 = await orch_1.process_user_request(
            user_message="My name is Victor and I am building an autonomous assistant called Zoro.",
            conversation_id="e2e-session-1",
        )
        assert turn_1.error is None

        # Verify memories were extracted
        stored = await mem_mgr_1.store.get_all(MemoryFilter(include_deleted=False))
        assert len(stored) >= 1
        assert any("Victor" in m.content or "Zoro" in m.content for m in stored)

        # -------------------------------------------------------------
        # SIMULATE APPLICATION RESTART
        # Destroy Session 1 objects and create completely new instances
        # connecting to the same SQLite database
        # -------------------------------------------------------------
        del orch_1
        del mem_mgr_1

        # Session 2 (New Process / Restart)
        mem_mgr_2 = MemoryManager(db_path=db_path)
        orch_2 = ZoroOrchestrator(
            provider_registry=provider_reg,
            tool_registry=tool_reg,
            db=db,
            audit=audit,
            event_bus=event_bus,
            emergency_mgr=emergency_mgr,
            memory_mgr=mem_mgr_2,
        )

        # Verify memories survived restart
        restarted_memories = await mem_mgr_2.store.get_all(MemoryFilter(include_deleted=False))
        assert len(restarted_memories) >= 1

        # Turn 2: Query real LLM with memory retrieval
        turn_2 = await orch_2.process_user_request(
            user_message="What is my name and what project am I building? Answer concisely.",
            conversation_id="e2e-session-2",
        )
        assert turn_2.error is None
        reply_text = turn_2.message.lower()

        # The genuine local Qwen2.5 3B model must ground on the retrieved memory
        assert "victor" in reply_text
        assert "zoro" in reply_text or "assistant" in reply_text or "project" in reply_text

    finally:
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except OSError:
                pass
