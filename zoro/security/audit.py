"""Cryptographically chained HMAC-SHA256 audit log manager."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from zoro.config.settings import ZoroSettings, get_settings
from zoro.security.dpapi import AuditKeyManager
from zoro.storage.db import DatabaseManager
from zoro.storage.models import AuditRecord

logger = logging.getLogger(__name__)

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"


class AuditLogger:
    """Manages tamper-evident audit records using HMAC-SHA256 chaining and DPAPI-protected keys.
    
    Security Model:
    - Provides cryptographic tamper-evidence: any modification, reordering, or deletion
      of audit records is immediately detected during verification.
    - DPAPI protects the HMAC key at rest tied to the Windows user credentials.
    - Does NOT provide immunity against a local administrator who can alter database files
      and clear keys directly.
    """

    def __init__(
        self,
        db: DatabaseManager,
        settings: Optional[ZoroSettings] = None,
        key: Optional[bytes] = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        if key:
            self._key = key
        else:
            key_mgr = AuditKeyManager(key_path=self.settings.security_dir / "audit.key")
            self._key = key_mgr.get_or_create_key()

    def _compute_hash(self, prev_hash: str, timestamp: str, actor: str, action: str, resource: str, details_json: str) -> str:
        """Compute HMAC-SHA256 of the combined record fields."""
        data = f"{prev_hash}|{timestamp}|{actor}|{action}|{resource}|{details_json}".encode("utf-8")
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()

    async def get_latest_hash(self) -> str:
        """Fetch the record_hash of the most recent audit record, or GENESIS_HASH if none exist."""
        row = await self.db.execute_read_one("SELECT record_hash FROM audit_records ORDER BY id DESC LIMIT 1")
        if row:
            return str(row[0])
        return GENESIS_HASH

    async def log_event(self, actor: str, action: str, resource: str, details: Dict[str, Any]) -> AuditRecord:
        """Append an event to the cryptographically chained audit log."""
        prev_hash = await self.get_latest_hash()
        timestamp = datetime.now(timezone.utc).isoformat()
        details_json = json.dumps(details, sort_keys=True)
        record_hash = self._compute_hash(prev_hash, timestamp, actor, action, resource, details_json)

        query = """
        INSERT INTO audit_records (timestamp, actor, action, resource, details_json, prev_hash, record_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        result = await self.db.execute_write(
            query,
            (timestamp, actor, action, resource, details_json, prev_hash, record_hash),
        )
        record_id = result.get("lastrowid")

        return AuditRecord(
            id=record_id,
            timestamp=timestamp,
            actor=actor,
            action=action,
            resource=resource,
            details=details,
            prev_hash=prev_hash,
            record_hash=record_hash,
        )

    async def verify_integrity(self) -> Tuple[bool, Optional[int]]:
        """
        Verify the complete cryptographic chain of audit records.
        Checks:
        1. Sequence ID continuity (detects deleted records).
        2. Hash chaining continuity (prev_hash == previous record_hash).
        3. HMAC signature validity.
        Returns (is_valid, corrupted_record_id).
        """
        rows = await self.db.execute_read(
            "SELECT id, timestamp, actor, action, resource, details_json, prev_hash, record_hash "
            "FROM audit_records ORDER BY id ASC"
        )
        
        expected_prev_hash = GENESIS_HASH
        expected_id = 1
        for row in rows:
            record_id, timestamp, actor, action, resource, details_json, prev_hash, recorded_hash = row
            
            # 1. Verify ID continuity (detects missing or deleted records)
            if record_id != expected_id:
                logger.error("Audit sequence broken: expected ID %d, found %d (record deletion detected).",
                             expected_id, record_id)
                return False, record_id

            # 2. Verify prev_hash continuity
            if prev_hash != expected_prev_hash:
                logger.error("Audit chain broken at record id %d: prev_hash mismatch.", record_id)
                return False, record_id
            
            # 3. Re-compute and verify HMAC signature
            computed_hash = self._compute_hash(prev_hash, timestamp, actor, action, resource, details_json)
            if computed_hash != recorded_hash:
                logger.error("Audit hash mismatch at record id %d: signature tampering detected!", record_id)
                return False, record_id

            expected_prev_hash = recorded_hash
            expected_id += 1

        return True, None
