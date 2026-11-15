"""Async SQLite Storage Engine implementing the Single-Writer Actor pattern with WAL mode."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import aiosqlite

from zoro.config.settings import ZoroSettings, get_settings
from zoro.storage.migrations import MigrationRunner

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite concurrency via WAL mode and a Single-Writer Actor."""

    def __init__(self, db_path: Optional[Path | str] = None, settings: Optional[ZoroSettings] = None) -> None:
        self.settings = settings or get_settings()
        self.db_path = Path(db_path) if db_path else self.settings.db_path
        self._write_conn: Optional[aiosqlite.Connection] = None
        self._read_conn: Optional[aiosqlite.Connection] = None
        self._write_queue: asyncio.Queue[
            Tuple[Any, Any, str, asyncio.Future]
        ] = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._accepting_writes = False

    async def _configure_connection(self, conn: aiosqlite.Connection, read_only: bool = False) -> None:
        """Apply performance and concurrency PRAGMAs."""
        await conn.execute("PRAGMA journal_mode = WAL;")
        await conn.execute(f"PRAGMA synchronous = {self.settings.db_synchronous};")
        await conn.execute(f"PRAGMA busy_timeout = {self.settings.db_busy_timeout_ms};")
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute(f"PRAGMA cache_size = -{self.settings.db_cache_size_kb};")
        if read_only:
            await conn.execute("PRAGMA query_only = ON;")

    async def initialize(self) -> None:
        """Initialize database, run migrations, and start the write actor."""
        if self._is_running:
            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 1. Establish primary write connection
        self._write_conn = await aiosqlite.connect(self.db_path)
        await self._configure_connection(self._write_conn, read_only=False)

        # 2. Run migrations using the write connection
        applied = await MigrationRunner.run_migrations(self._write_conn)
        logger.info("Database initialized at %s (%d migrations applied).", self.db_path, applied)

        # 3. Establish dedicated read connection
        self._read_conn = await aiosqlite.connect(self.db_path)
        await self._configure_connection(self._read_conn, read_only=True)

        # 4. Start background single-writer actor
        self._is_running = True
        self._accepting_writes = True
        self._writer_task = asyncio.create_task(self._writer_loop(), name="zoro-sqlite-writer")

    async def _writer_loop(self) -> None:
        """Dedicated background worker sequentially executing write operations."""
        logger.debug("SQLite single-writer actor loop started.")
        while self._is_running or not self._write_queue.empty():
            try:
                item = await self._write_queue.get()
                query, params, op_type, future = item

                try:
                    assert self._write_conn is not None
                    if op_type == "executemany":
                        cursor = await self._write_conn.executemany(query, params)
                        await self._write_conn.commit()
                        result = {"lastrowid": cursor.lastrowid, "rowcount": cursor.rowcount}
                    elif op_type == "transaction":
                        # params is a list of (sql, params_tuple)
                        last_id = None
                        total_rows = 0
                        for sql_stmt, stmt_params in params:
                            c = await self._write_conn.execute(sql_stmt, stmt_params)
                            last_id = c.lastrowid
                            total_rows += c.rowcount
                        await self._write_conn.commit()
                        result = {"lastrowid": last_id, "rowcount": total_rows}
                    else:
                        cursor = await self._write_conn.execute(query, params)
                        await self._write_conn.commit()
                        result = {"lastrowid": cursor.lastrowid, "rowcount": cursor.rowcount}

                    if not future.done():
                        future.set_result(result)
                except Exception as exc:
                    try:
                        if self._write_conn:
                            await self._write_conn.rollback()
                    except Exception as rb_err:
                        logger.error("Error during rollback: %s", rb_err)
                    if not future.done():
                        future.set_exception(exc)
                finally:
                    self._write_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in SQLite writer loop: %s", e, exc_info=True)

    async def execute_write(self, query: str, params: Tuple[Any, ...] = ()) -> Dict[str, Any]:
        """Submit a single write query to the serialized write actor and await completion."""
        if not self._accepting_writes:
            raise RuntimeError("DatabaseManager is not accepting writes.")
        
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._write_queue.put((query, params, "single", future))
        return await future

    async def execute_write_many(self, query: str, params_seq: List[Tuple[Any, ...]]) -> Dict[str, Any]:
        """Submit an executemany write query to the serialized write actor and await completion."""
        if not self._accepting_writes:
            raise RuntimeError("DatabaseManager is not accepting writes.")
        
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._write_queue.put((query, params_seq, "executemany", future))
        return await future

    async def execute_transaction(self, operations: List[Tuple[str, Tuple[Any, ...]]]) -> Dict[str, Any]:
        """Submit a batch of queries to execute atomically in a single transaction."""
        if not self._accepting_writes:
            raise RuntimeError("DatabaseManager is not accepting writes.")
        
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._write_queue.put(("", operations, "transaction", future))
        return await future

    async def execute_read(self, query: str, params: Tuple[Any, ...] = ()) -> List[Tuple[Any, ...]]:
        """Execute a read query directly on the dedicated read connection."""
        if not self._read_conn:
            raise RuntimeError("DatabaseManager is not initialized.")
        
        cursor = await self._read_conn.execute(query, params)
        return await cursor.fetchall()

    async def execute_read_one(self, query: str, params: Tuple[Any, ...] = ()) -> Optional[Tuple[Any, ...]]:
        """Execute a read query returning a single row."""
        if not self._read_conn:
            raise RuntimeError("DatabaseManager is not initialized.")
        
        cursor = await self._read_conn.execute(query, params)
        return await cursor.fetchone()

    async def checkpoint(self) -> None:
        """Force a WAL checkpoint to truncate or merge the WAL file."""
        if self._write_conn:
            await self._write_conn.execute("PRAGMA wal_checkpoint(PASSIVE);")

    async def close(self) -> None:
        """Gracefully drain the write queue, checkpoint WAL, and close connections."""
        self._accepting_writes = False
        if self._writer_task:
            await self._write_queue.join()
            self._is_running = False
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
            self._writer_task = None

        if self._write_conn:
            await self.checkpoint()
            await self._write_conn.close()
            self._write_conn = None

        if self._read_conn:
            await self._read_conn.close()
            self._read_conn = None
        
        logger.info("DatabaseManager closed cleanly.")
