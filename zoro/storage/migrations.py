"""Deterministic SQLite migration engine with SHA-256 checksum verification."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple
import aiosqlite

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Raised when migration fails or checksum tampering is detected."""
    pass


class MigrationRunner:
    """Manages ordered, versioned SQLite migrations with integrity verification."""

    MIGRATIONS_DIR = Path(__file__).parent / "sql"

    MIGRATION_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        checksum TEXT NOT NULL,
        applied_at TEXT NOT NULL
    );
    """

    @classmethod
    def compute_checksum(cls, content: str) -> str:
        """Compute SHA-256 checksum of normalized SQL content."""
        normalized = content.strip().replace("\r\n", "\n")
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @classmethod
    def get_migration_files(cls, migrations_dir: Optional[Path] = None) -> List[Tuple[int, str, Path]]:
        """Return list of (version, name, file_path) sorted by version."""
        target_dir = migrations_dir or cls.MIGRATIONS_DIR
        if not target_dir.exists():
            return []
        
        migrations = []
        for file in target_dir.glob("*.sql"):
            # Expecting filename format: 001_name.sql
            parts = file.stem.split("_", 1)
            if len(parts) == 2 and parts[0].isdigit():
                version = int(parts[0])
                name = parts[1]
                migrations.append((version, name, file))
        
        return sorted(migrations, key=lambda x: x[0])

    @classmethod
    async def run_migrations(cls, conn: aiosqlite.Connection, migrations_dir: Optional[Path] = None) -> int:
        """Apply all pending migrations to the database. Returns count of applied migrations."""
        await conn.execute(cls.MIGRATION_TABLE_DDL)
        await conn.commit()

        # Query existing applied migrations
        cursor = await conn.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version ASC"
        )
        applied = {row[0]: (row[1], row[2]) for row in await cursor.fetchall()}

        migration_files = cls.get_migration_files(migrations_dir=migrations_dir)
        applied_count = 0

        for version, name, path in migration_files:
            content = path.read_text(encoding="utf-8")
            checksum = cls.compute_checksum(content)

            if version in applied:
                applied_name, applied_checksum = applied[version]
                if applied_checksum != checksum:
                    raise MigrationError(
                        f"Migration tampering detected for version {version} ({name})! "
                        f"Expected {applied_checksum}, found {checksum}."
                    )
                continue

            # Apply pending migration within explicit transaction
            logger.info("Applying migration %03d_%s...", version, name)
            try:
                await conn.executescript(content)
                now = datetime.now(timezone.utc).isoformat()
                await conn.execute(
                    "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (version, name, checksum, now),
                )
                await conn.commit()
                applied_count += 1
                logger.info("Migration %03d_%s applied successfully.", version, name)
            except Exception as e:
                try:
                    await conn.rollback()
                except Exception:
                    pass
                raise MigrationError(f"Failed to apply migration {version}_{name}: {e}") from e

        return applied_count
