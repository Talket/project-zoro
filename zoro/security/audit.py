"""Cryptographically chained HMAC-SHA256 audit log manager with trusted checkpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from zoro.config.settings import ZoroSettings, get_settings
from zoro.security.dpapi import AuditKeyManager
from zoro.storage.db import DatabaseManager
from zoro.storage.models import AuditRecord

logger = logging.getLogger(__name__)

GENESIS_HASH = "0000000000000000000000000000000000000000000000000000000000000000"
CHECKPOINT_VERSION = 1


class AuditLogger:
    """Manages tamper-evident audit records using HMAC-SHA256 chaining, DPAPI keys, and trusted checkpoints.
    
    Security Model & Boundaries:
    - Tamper-Evidence: Cryptographic chaining + independent trusted checkpoint detect record
      modifications, out-of-order records, middle deletions, and tail truncations.
    - Checkpoint Protection: Checkpoint is stored independently in the security directory,
      HMAC-signed using the DPAPI-protected key, and updated atomically (fsync + replace).
    - Failure Mode: Fails closed on any inconsistency, signature mismatch, or corrupted checkpoint.
    - Honest Boundary: Protects against offline inspection and accidental/sub-agent tampering.
      Does not provide runtime immunity against malicious code running under the same Windows user
      session with full privileges, or local Administrators who can rewrite both DB and checkpoint.
    """

    def __init__(
        self,
        db: DatabaseManager,
        settings: Optional[ZoroSettings] = None,
        key: Optional[bytes] = None,
        checkpoint_path: Optional[Path] = None,
    ) -> None:
        self.db = db
        self.settings = settings or get_settings()
        if checkpoint_path:
            self.checkpoint_path = Path(checkpoint_path)
        else:
            self.checkpoint_path = Path(self.settings.audit_checkpoint_path)

        if key:
            self._key = key
        else:
            key_mgr = AuditKeyManager(key_path=self.settings.security_dir / "audit.key")
            self._key = key_mgr.get_or_create_key()

    def _compute_hash(self, prev_hash: str, timestamp: str, actor: str, action: str, resource: str, details_json: str) -> str:
        """Compute HMAC-SHA256 of the combined record fields."""
        data = f"{prev_hash}|{timestamp}|{actor}|{action}|{resource}|{details_json}".encode("utf-8")
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()

    def _compute_checkpoint_signature(self, version: int, last_seq: int, last_hash: str, updated_at: str) -> str:
        """Compute HMAC-SHA256 signature for the checkpoint payload."""
        data = f"CHECKPOINT|v{version}|seq:{last_seq}|hash:{last_hash}|ts:{updated_at}".encode("utf-8")
        return hmac.new(self._key, data, hashlib.sha256).hexdigest()

    def write_checkpoint(self, last_sequence_id: int, last_record_hash: str) -> None:
        """Atomically persist a signed audit checkpoint outside the database."""
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        updated_at = datetime.now(timezone.utc).isoformat()
        signature = self._compute_checkpoint_signature(
            CHECKPOINT_VERSION, last_sequence_id, last_record_hash, updated_at
        )
        checkpoint_data = {
            "version": CHECKPOINT_VERSION,
            "last_sequence_id": last_sequence_id,
            "last_record_hash": last_record_hash,
            "updated_at": updated_at,
            "signature": signature,
        }
        payload_bytes = json.dumps(checkpoint_data, indent=2).encode("utf-8")

        temp_path = self.checkpoint_path.with_name(
            f"{self.checkpoint_path.name}.tmp.{os.getpid()}.{secrets.token_hex(4)}"
        )
        try:
            with open(temp_path, "wb") as f:
                f.write(payload_bytes)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, self.checkpoint_path)
            logger.debug("Committed audit checkpoint: seq=%d", last_sequence_id)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def read_checkpoint(self) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """
        Read and verify the trusted audit checkpoint.
        Returns (is_valid, data_dict, status_message).
        """
        if not self.checkpoint_path.exists():
            return True, None, "No checkpoint file present (genesis state)."

        try:
            raw_bytes = self.checkpoint_path.read_bytes()
            if not raw_bytes:
                return False, None, "Checkpoint file is empty (interrupted write)."

            data = json.loads(raw_bytes.decode("utf-8"))
            version = data.get("version")
            last_seq = data.get("last_sequence_id")
            last_hash = data.get("last_record_hash")
            updated_at = data.get("updated_at")
            signature = data.get("signature")

            if version is None or last_seq is None or last_hash is None or not signature or not updated_at:
                return False, None, "Checkpoint file has missing or invalid required fields."

            expected_sig = self._compute_checkpoint_signature(version, last_seq, last_hash, updated_at)
            if not hmac.compare_digest(expected_sig, signature):
                return False, None, "Checkpoint signature mismatch: checkpoint tampering detected."

            return True, data, "Checkpoint verified successfully."
        except Exception as e:
            return False, None, f"Checkpoint read or decoding error: {e}"

    async def get_latest_hash(self) -> str:
        """Fetch the record_hash of the most recent audit record, or GENESIS_HASH if none exist."""
        row = await self.db.execute_read_one("SELECT record_hash FROM audit_records ORDER BY id DESC LIMIT 1")
        if row:
            return str(row[0])
        return GENESIS_HASH

    async def log_event(self, actor: str, action: str, resource: str, details: Dict[str, Any]) -> AuditRecord:
        """Append an event to the cryptographically chained audit log and update checkpoint."""
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

        # Update the external trusted checkpoint atomically
        self.write_checkpoint(record_id, record_hash)

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
        Verify the complete cryptographic chain of audit records against the trusted checkpoint.
        Checks:
        1. Checkpoint integrity & HMAC signature (detects checkpoint tampering).
        2. Database tail bounds against checkpoint (detects tail truncation/deletion).
        3. Sequence ID continuity (detects middle record deletions).
        4. Hash chaining continuity (prev_hash == previous record_hash).
        5. Record HMAC signature validity (detects record modifications).
        Returns (is_valid, corrupted_record_id).
        """
        # 1. Verify Checkpoint
        cp_valid, cp_data, cp_msg = self.read_checkpoint()
        if not cp_valid:
            logger.error("Audit verification failed: %s", cp_msg)
            return False, None

        rows = await self.db.execute_read(
            "SELECT id, timestamp, actor, action, resource, details_json, prev_hash, record_hash "
            "FROM audit_records ORDER BY id ASC"
        )

        # 2. Check empty DB vs checkpoint
        if not rows:
            if cp_data and cp_data.get("last_sequence_id", 0) > 0:
                logger.error(
                    "Audit verification failed: Checkpoint expects %d records, but database is empty (tail/full deletion).",
                    cp_data["last_sequence_id"],
                )
                return False, cp_data["last_sequence_id"]
            return True, None

        # If rows exist, a valid checkpoint MUST exist
        if cp_data is None:
            logger.error("Audit verification failed: Audit database contains records, but no checkpoint exists.")
            return False, rows[-1][0]

        # 3. Check tail record against checkpoint
        cp_seq = cp_data["last_sequence_id"]
        cp_hash = cp_data["last_record_hash"]
        db_last_id = rows[-1][0]
        db_last_hash = rows[-1][7]

        if db_last_id != cp_seq:
            logger.error("Audit tail deletion detected: database ends at ID %d, checkpoint expects ID %d.",
                         db_last_id, cp_seq)
            return False, cp_seq

        if db_last_hash != cp_hash:
            logger.error("Audit tail tampering detected: database last hash mismatch with checkpoint.")
            return False, db_last_id

        # 4. Verify sequence continuity, hash chaining, and record HMAC signatures
        expected_prev_hash = GENESIS_HASH
        expected_id = 1
        for row in rows:
            record_id, timestamp, actor, action, resource, details_json, prev_hash, recorded_hash = row

            if record_id != expected_id:
                logger.error("Audit sequence broken: expected ID %d, found %d (record deletion detected).",
                             expected_id, record_id)
                return False, record_id

            if prev_hash != expected_prev_hash:
                logger.error("Audit chain broken at record id %d: prev_hash mismatch.", record_id)
                return False, record_id

            computed_hash = self._compute_hash(prev_hash, timestamp, actor, action, resource, details_json)
            if computed_hash != recorded_hash:
                logger.error("Audit hash mismatch at record id %d: signature tampering detected!", record_id)
                return False, record_id

            expected_prev_hash = recorded_hash
            expected_id += 1

        return True, None
