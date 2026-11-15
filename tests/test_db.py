"""Comprehensive tests for SQLite storage, migrations, and concurrency."""

import asyncio
from pathlib import Path
import pytest
from zoro.config.settings import ZoroSettings
from zoro.storage.db import DatabaseManager
from zoro.storage.migrations import MigrationError, MigrationRunner


@pytest.mark.asyncio
async def test_fresh_database_creation(temp_dir):
    """1. Fresh database creation with migrations and WAL mode."""
    db_path = temp_dir / "fresh.db"
    assert not db_path.exists()

    settings = ZoroSettings(data_dir=temp_dir, db_path=db_path)
    db = DatabaseManager(db_path=db_path, settings=settings)
    await db.initialize()

    assert db_path.exists()
    row = await db.execute_read_one("PRAGMA journal_mode;")
    assert row[0].lower() == "wal"

    # Check migration table exists
    migrations = await db.execute_read("SELECT version, name FROM schema_migrations ORDER BY version ASC")
    assert len(migrations) >= 2
    assert migrations[0][0] == 1
    assert migrations[1][0] == 2

    await db.close()


@pytest.mark.asyncio
async def test_existing_database_reopening_and_persistence(temp_dir):
    """2 & 7. Reopening existing database and verifying persisted data."""
    db_path = temp_dir / "persistent.db"
    settings = ZoroSettings(data_dir=temp_dir, db_path=db_path)

    # First session: insert data
    db1 = DatabaseManager(db_path=db_path, settings=settings)
    await db1.initialize()
    await db1.execute_write(
        "INSERT INTO config_entries (key, value, updated_at) VALUES (?, ?, ?)",
        ("theme", "dark_obsidian", "2026-11-15T12:00:00Z"),
    )
    await db1.close()

    # Second session: reopen and verify data persisted
    db2 = DatabaseManager(db_path=db_path, settings=settings)
    await db2.initialize()
    row = await db2.execute_read_one("SELECT value FROM config_entries WHERE key = ?", ("theme",))
    assert row is not None
    assert row[0] == "dark_obsidian"
    await db2.close()


@pytest.mark.asyncio
async def test_sequential_custom_migrations(temp_dir):
    """3. Sequential migrations from custom migration files."""
    mig_dir = temp_dir / "custom_sql"
    mig_dir.mkdir(parents=True, exist_ok=True)

    (mig_dir / "001_first.sql").write_text("CREATE TABLE test_first (id INTEGER PRIMARY KEY);", encoding="utf-8")
    (mig_dir / "002_second.sql").write_text("CREATE TABLE test_second (name TEXT);", encoding="utf-8")

    db_path = temp_dir / "custom_mig.db"
    settings = ZoroSettings(data_dir=temp_dir, db_path=db_path)
    db = DatabaseManager(db_path=db_path, settings=settings)
    
    # Establish connection
    import aiosqlite
    conn = await aiosqlite.connect(db_path)
    count = await MigrationRunner.run_migrations(conn, migrations_dir=mig_dir)
    assert count == 2

    # Verify tables exist
    cursor = await conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'test_%'")
    tables = [r[0] for r in await cursor.fetchall()]
    assert "test_first" in tables
    assert "test_second" in tables
    await conn.close()


@pytest.mark.asyncio
async def test_migration_checksum_tamper_detection(test_db, monkeypatch):
    """4. Migration checksum mismatch raises MigrationError."""
    original_fn = MigrationRunner.compute_checksum
    monkeypatch.setattr(MigrationRunner, "compute_checksum", lambda content: "tampered_checksum_xyz")

    with pytest.raises(MigrationError) as exc_info:
        await MigrationRunner.run_migrations(test_db._write_conn)
    assert "tampering detected" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_transaction_rollback_on_failure(test_db):
    """5. Atomic transaction rollback when a statement fails."""
    # Attempt atomic transaction where statement 2 fails
    ops = [
        ("INSERT INTO config_entries (key, value, updated_at) VALUES (?, ?, ?)", ("k1", "v1", "now")),
        ("INSERT INTO non_existent_table (x) VALUES (?)", ("error",)),
    ]

    with pytest.raises(Exception):
        await test_db.execute_transaction(ops)

    # Verify statement 1 was rolled back
    row = await test_db.execute_read_one("SELECT value FROM config_entries WHERE key = ?", ("k1",))
    assert row is None


@pytest.mark.asyncio
async def test_serialized_writer_concurrency_50_tasks(test_db):
    """6. Concurrent writes from at least 50 async tasks succeed without locking errors."""
    async def worker(index: int):
        return await test_db.execute_write(
            "INSERT INTO system_events (timestamp, category, event_type, payload_json) VALUES (?, ?, ?, ?)",
            (f"2026-11-15T12:00:{index:02d}", "stress", "CONCURRENCY_50", f'{{"task": {index}}}'),
        )

    tasks = [worker(i) for i in range(50)]
    results = await asyncio.gather(*tasks)
    assert len(results) == 50

    # Verify all 50 were inserted
    rows = await test_db.execute_read("SELECT count(*) FROM system_events WHERE event_type = 'CONCURRENCY_50'")
    assert rows[0][0] == 50


@pytest.mark.asyncio
async def test_database_shutdown_with_pending_operations(temp_dir):
    """8. Database shutdown gracefully drains and commits pending operations."""
    db_path = temp_dir / "drain.db"
    settings = ZoroSettings(data_dir=temp_dir, db_path=db_path)
    db = DatabaseManager(db_path=db_path, settings=settings)
    await db.initialize()

    # Queue multiple writes concurrently
    tasks = [
        asyncio.create_task(
            db.execute_write(
                "INSERT INTO config_entries (key, value, updated_at) VALUES (?, ?, ?)",
                (f"drain_{i}", f"val_{i}", "now"),
            )
        )
        for i in range(10)
    ]
    # Yield control to let tasks enqueue into _write_queue
    await asyncio.sleep(0)

    # Immediately call close() - it must drain the queue cleanly
    await db.close()
    await asyncio.gather(*tasks)

    # Verify all were committed by reopening
    db2 = DatabaseManager(db_path=db_path, settings=settings)
    await db2.initialize()
    rows = await db2.execute_read("SELECT count(*) FROM config_entries WHERE key LIKE 'drain_%'")
    assert rows[0][0] == 10
    await db2.close()


@pytest.mark.asyncio
async def test_database_execute_many_and_idempotent_init(temp_dir):
    """9. Database execute_many batching and idempotent initialize()."""
    db_path = temp_dir / "batch.db"
    settings = ZoroSettings(data_dir=temp_dir, db_path=db_path)
    db = DatabaseManager(db_path=db_path, settings=settings)

    await db.initialize()
    # Calling initialize again while running should be a no-op
    await db.initialize()

    # Batch insert with execute_write_many
    batch = [(f"batch_{i}", f"val_{i}", "2026-01-01") for i in range(10)]
    res = await db.execute_write_many(
        "INSERT INTO config_entries (key, value, updated_at) VALUES (?, ?, ?)",
        batch,
    )
    assert res["rowcount"] == 10

    # Query back
    rows = await db.execute_read("SELECT count(*) FROM config_entries WHERE key LIKE 'batch_%'")
    assert rows[0][0] == 10

    await db.close()
