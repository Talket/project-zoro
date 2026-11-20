"""Integration tests verifying Persistent Memory within the Central Orchestrator and Engine."""

from __future__ import annotations

import os
import tempfile
import pytest
import aiosqlite

from zoro.core.event_bus import AsyncEventBus
from zoro.memory.manager import MemoryManager
from zoro.memory.models import MemoryCategory, MemoryCreate, MemoryFilter
from zoro.models.mock import MockModelProvider
from zoro.models.registry import ProviderRegistry
from zoro.orchestrator.orchestrator import ZoroOrchestrator
from zoro.security.audit import AuditLogger
from zoro.security.emergency import EmergencyManager
from zoro.security.permissions import PermissionGate
from zoro.storage.db import DatabaseManager
from zoro.storage.migrations import MigrationRunner
from zoro.tools.registry import ToolRegistry


@pytest.fixture
async def memory_env():
    """Build an integrated Orchestrator test environment with real SQLite and MemoryManager."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        db_path = tf.name

    async with aiosqlite.connect(db_path) as conn:
        await MigrationRunner.run_migrations(conn)

    provider_reg = ProviderRegistry()
    mock_prov = MockModelProvider()
    provider_reg.register_provider("mock", mock_prov, default_model="mock-v1")
    provider_reg.set_active_provider("mock")

    db = DatabaseManager()
    audit = AuditLogger(db)
    perms = PermissionGate()
    tool_reg = ToolRegistry(db, audit, perms)
    event_bus = AsyncEventBus()
    emergency_mgr = EmergencyManager()

    memory_mgr = MemoryManager(db_path=db_path)
    orchestrator = ZoroOrchestrator(
        provider_registry=provider_reg,
        tool_registry=tool_reg,
        db=db,
        audit=audit,
        event_bus=event_bus,
        emergency_mgr=emergency_mgr,
        memory_mgr=memory_mgr,
    )

    yield orchestrator, memory_mgr, db_path

    if os.path.exists(db_path):
        try:
            os.unlink(db_path)
        except OSError:
            pass


@pytest.mark.asyncio
async def test_orchestrator_memory_grounding(memory_env) -> None:
    """Verify that stored memories are injected and referenced during conversation."""
    orchestrator, memory_mgr, _ = memory_env

    # 1. Store a project memory
    await memory_mgr.store.create_memory(
        MemoryCreate(
            category=MemoryCategory.PROJECT,
            content="The user is building Project Zoro with SQLite and local Ollama Qwen2.5.",
            project_name="Zoro",
            importance=0.9,
        )
    )

    # 2. Query orchestrator about projects
    resp = await orchestrator.process_user_request(
        user_message="Zoro, what project am I working on?",
        conversation_id="conv-mem-test-1",
    )
    assert resp.error is None
    # Reply should reference the persistent memory
    assert "Zoro" in resp.message or "SQLite" in resp.message


@pytest.mark.asyncio
async def test_orchestrator_turn_extraction(memory_env) -> None:
    """Verify that completed turns extract new personal facts into memory."""
    orchestrator, memory_mgr, _ = memory_env

    # Turn 1: User states their preferred programming language
    resp = await orchestrator.process_user_request(
        user_message="Remember that I prefer Rust for systems programming.",
        conversation_id="conv-mem-test-2",
    )
    assert resp.error is None

    # Verify memory was persisted
    memories = await memory_mgr.store.get_all(MemoryFilter(category=MemoryCategory.PREFERENCE))
    assert len(memories) >= 1
    assert any("Rust" in m.content for m in memories)


@pytest.mark.asyncio
async def test_memory_engine_rpc_handlers(memory_env) -> None:
    """Verify that the engine's Named Pipe RPC handlers for memory operate as expected."""
    from zoro.config.settings import ZoroSettings
    from zoro.core.engine import ZoroEngine

    _, _, db_path = memory_env
    settings = ZoroSettings(db_path=db_path)
    engine = ZoroEngine(settings=settings)

    # 1. memory.create
    res_create = await engine._rpc_memory_create({
        "category": "IDENTITY",
        "content": "Owner's preferred title is Architect.",
        "importance": 0.85,
    })
    assert res_create["success"] is True
    mem_id = res_create["memory"]["id"]

    # 2. memory.get_all
    res_get = await engine._rpc_memory_get_all({"category": "IDENTITY"})
    assert res_get["success"] is True
    assert len(res_get["memories"]) >= 1

    # 3. memory.search
    res_search = await engine._rpc_memory_search({"query": "Architect", "min_score": 0.1})
    assert res_search["success"] is True
    assert len(res_search["results"]) >= 1

    # 4. memory.update
    res_update = await engine._rpc_memory_update({
        "id": mem_id,
        "content": "Owner's preferred title is Chief Architect.",
    })
    assert res_update["success"] is True
    assert "Chief" in res_update["memory"]["content"]

    # 5. memory.delete
    res_del = await engine._rpc_memory_delete({"id": mem_id})
    assert res_del["success"] is True

    # 6. memory.clear_all with invalid confirmation
    res_clear_bad = await engine._rpc_memory_clear_all({"confirmation_phrase": "wrong"})
    assert res_clear_bad["success"] is False

    # 7. memory.clear_all with correct confirmation
    res_clear_good = await engine._rpc_memory_clear_all({"confirmation_phrase": "CONFIRM_CLEAR_ALL_MEMORIES"})
    assert res_clear_good["success"] is True
