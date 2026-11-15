"""Tests for Milestone 02 Intelligence Core database schema, tables, and constraints."""

from __future__ import annotations

from pathlib import Path
import pytest
from zoro.storage.db import DatabaseManager


@pytest.mark.asyncio
async def test_intelligence_schema_tables_and_crud(tmp_path: Path):
    db_file = tmp_path / "test_intel.db"
    db = DatabaseManager(db_path=db_file)
    await db.initialize()

    try:
        # 1. ai_providers
        await db.execute_write(
            """
            INSERT INTO ai_providers (id, provider_type, base_url, is_enabled, default_model, capabilities_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ollama", "ollama", "http://127.0.0.1:11434", 1, "qwen2.5:3b", '{"supports_tools": true}', "2026-11-16T00:00:00Z", "2026-11-16T00:00:00Z"),
        )
        provider = await db.execute_read_one("SELECT id, provider_type, is_enabled FROM ai_providers WHERE id = ?", ("ollama",))
        assert provider is not None
        assert provider[0] == "ollama"
        assert provider[1] == "ollama"
        assert provider[2] == 1

        # 2. ai_models
        await db.execute_write(
            """
            INSERT INTO ai_models (id, provider_id, model_name, context_window, parameter_size, quantization, is_local, capabilities_json, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("ollama/qwen2.5:3b", "ollama", "qwen2.5:3b", 32768, "3B", "Q4_K_M", 1, '{"tools": true}', "2026-11-16T00:00:00Z"),
        )
        model = await db.execute_read_one("SELECT model_name, context_window FROM ai_models WHERE id = ?", ("ollama/qwen2.5:3b",))
        assert model is not None
        assert model[0] == "qwen2.5:3b"
        assert model[1] == 32768

        # 3. model_benchmarks
        await db.execute_write(
            """
            INSERT INTO model_benchmarks (model_name, provider_id, timestamp, ttft_ms, tokens_per_sec, ram_used_mb, vram_used_mb, gpu_temp_c, structured_json_score, instruction_following_score, tool_calling_supported, raw_metrics_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("qwen2.5:3b", "ollama", "2026-11-16T00:00:00Z", 42.5, 38.2, 2048.0, 1850.0, 48.0, 0.98, 0.95, 1, '{"latency_ms": 42.5}'),
        )
        bench = await db.execute_read_one("SELECT tokens_per_sec, tool_calling_supported FROM model_benchmarks WHERE model_name = ?", ("qwen2.5:3b",))
        assert bench is not None
        assert bench[0] == 38.2
        assert bench[1] == 1

        # 4. conversations & messages
        conv_id = "conv-101"
        await db.execute_write(
            "INSERT INTO conversations (id, title, created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?, ?)",
            (conv_id, "Test Chat", "2026-11-16T00:00:00Z", "2026-11-16T00:00:00Z", "{}"),
        )
        await db.execute_write(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conv_id, "user", "Hello ZORO", "2026-11-16T00:00:00Z"),
        )
        await db.execute_write(
            "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (conv_id, "assistant", "Greetings, Sir. How may I assist you?", "2026-11-16T00:00:01Z"),
        )
        msgs = await db.execute_read("SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id ASC", (conv_id,))
        assert len(msgs) == 2
        assert msgs[0][0] == "user"
        assert msgs[1][0] == "assistant"

        # 5. task_plans & task_steps
        plan_id = "plan-901"
        await db.execute_write(
            "INSERT INTO task_plans (id, conversation_id, user_request, status, plan_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (plan_id, conv_id, "Find files and report", "EXECUTING", '{"steps": 2}', "2026-11-16T00:00:00Z", "2026-11-16T00:00:00Z"),
        )
        await db.execute_write(
            """
            INSERT INTO task_steps (id, plan_id, step_index, description, tool_name, input_json, status, requires_approval, approval_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("step-1", plan_id, 0, "Discover PDFs", "file_discovery", '{"pattern": "*.pdf"}', "COMPLETED", 0, None),
        )
        await db.execute_write(
            """
            INSERT INTO task_steps (id, plan_id, step_index, description, tool_name, input_json, status, requires_approval, approval_token)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("step-2", plan_id, 1, "Delete temp PDF", "file_delete", '{"path": "temp.pdf"}', "WAITING_FOR_APPROVAL", 1, "tok-xyz"),
        )
        steps = await db.execute_read("SELECT tool_name, requires_approval FROM task_steps WHERE plan_id = ? ORDER BY step_index ASC", (plan_id,))
        assert len(steps) == 2
        assert steps[0][0] == "file_discovery"
        assert steps[1][1] == 1

        # 6. tool_executions
        await db.execute_write(
            """
            INSERT INTO tool_executions (tool_name, step_id, input_json, output_json, status, error, duration_ms, executed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("file_discovery", "step-1", '{"pattern": "*.pdf"}', '{"files": ["report.pdf"]}', "SUCCESS", None, 14.2, "2026-11-16T00:00:02Z"),
        )
        exec_record = await db.execute_read_one("SELECT status FROM tool_executions WHERE tool_name = ?", ("file_discovery",))
        assert exec_record is not None
        assert exec_record[0] == "SUCCESS"

        # 7. approval_requests
        await db.execute_write(
            """
            INSERT INTO approval_requests (id, step_id, tool_name, permission_tier, description, token, status, requested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("appr-1", "step-2", "file_delete", "DESTRUCTIVE", "Delete temp.pdf", "tok-xyz", "PENDING", "2026-11-16T00:00:03Z"),
        )
        appr = await db.execute_read_one("SELECT status, permission_tier FROM approval_requests WHERE token = ?", ("tok-xyz",))
        assert appr is not None
        assert appr[0] == "PENDING"
        assert appr[1] == "DESTRUCTIVE"

        # 8. Test Cascade Deletion: Deleting conversation cascades to messages
        await db.execute_write("DELETE FROM conversations WHERE id = ?", (conv_id,))
        remaining_msgs = await db.execute_read("SELECT id FROM messages WHERE conversation_id = ?", (conv_id,))
        assert len(remaining_msgs) == 0

    finally:
        await db.close()
