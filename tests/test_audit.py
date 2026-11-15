"""Comprehensive tests for HMAC-SHA256 chained audit logging, trusted checkpoints, and DPAPI key management."""

import json
import pytest
from zoro.security.audit import AuditLogger, GENESIS_HASH
from zoro.security.dpapi import AuditKeyManager, dpapi_protect, dpapi_unprotect
from zoro.storage.db import DatabaseManager


def test_dpapi_protect_and_unprotect_roundtrip():
    """Verify DPAPI local encryption and decryption."""
    secret = b"super-secure-audit-key-32-bytes!"
    encrypted = dpapi_protect(secret, description="TestSecret")
    assert encrypted != secret
    decrypted = dpapi_unprotect(encrypted)
    assert decrypted == secret


def test_audit_key_manager_persistence(temp_dir):
    """Verify that AuditKeyManager generates a key and recovers it across runs."""
    key_file = temp_dir / "audit.key"
    mgr1 = AuditKeyManager(key_path=key_file)
    key1 = mgr1.get_or_create_key()
    assert len(key1) == 32
    assert key_file.exists()

    # Second instance recovers the same decrypted key
    mgr2 = AuditKeyManager(key_path=key_file)
    key2 = mgr2.get_or_create_key()
    assert key2 == key1


def test_audit_key_manager_fails_closed_on_corrupt_key(temp_dir):
    """Verify AuditKeyManager fails closed when key file exists but cannot be decrypted."""
    key_file = temp_dir / "audit.key"
    key_file.write_bytes(b"corrupted_non_dpapi_bytes_1234567890")

    mgr = AuditKeyManager(key_path=key_file)
    with pytest.raises(RuntimeError) as exc_info:
        mgr.get_or_create_key()
    assert "Failed to decrypt existing DPAPI audit key" in str(exc_info.value)
    # Ensure key file was NOT overwritten with a newly generated key
    assert key_file.read_bytes() == b"corrupted_non_dpapi_bytes_1234567890"


@pytest.mark.asyncio
async def test_audit_hash_chaining(test_db, test_settings, temp_dir):
    """Valid chain verification and record linkage."""
    key_mgr = AuditKeyManager(key_path=temp_dir / "audit.key")
    key = key_mgr.get_or_create_key()
    audit = AuditLogger(test_db, settings=test_settings, key=key)

    rec1 = await audit.log_event("User", "CREATE_FILE", "test.txt", {"path": "/tmp/test.txt"})
    assert rec1.prev_hash == GENESIS_HASH
    assert len(rec1.record_hash) == 64

    rec2 = await audit.log_event("Agent", "EDIT_FILE", "test.txt", {"diff": "+line"})
    assert rec2.prev_hash == rec1.record_hash

    is_valid, corrupted_id = await audit.verify_integrity()
    assert is_valid is True
    assert corrupted_id is None


@pytest.mark.asyncio
async def test_audit_modified_entry_detection(test_db, test_settings):
    """Detection of modified audit entry."""
    key = b"test_key_1234567890123456789012"
    audit = AuditLogger(test_db, settings=test_settings, key=key)

    rec1 = await audit.log_event("User", "ACTION_1", "res1", {})
    rec2 = await audit.log_event("User", "ACTION_2", "res2", {})
    rec3 = await audit.log_event("User", "ACTION_3", "res3", {})

    # Modify record 2 action
    await test_db.execute_write(
        "UPDATE audit_records SET action = 'TAMPERED_ACTION' WHERE id = ?",
        (rec2.id,),
    )

    is_valid, corrupted_id = await audit.verify_integrity()
    assert is_valid is False
    assert corrupted_id == rec2.id


@pytest.mark.asyncio
async def test_audit_deleted_entry_detection(test_db, test_settings):
    """Detection of deleted audit entries (middle deletion)."""
    key = b"test_key_1234567890123456789012"
    audit = AuditLogger(test_db, settings=test_settings, key=key)

    rec1 = await audit.log_event("User", "ACTION_1", "res1", {})
    rec2 = await audit.log_event("User", "ACTION_2", "res2", {})
    rec3 = await audit.log_event("User", "ACTION_3", "res3", {})

    # Delete record 2 (middle deletion)
    await test_db.execute_write("DELETE FROM audit_records WHERE id = ?", (rec2.id,))

    is_valid, corrupted_id = await audit.verify_integrity()
    assert is_valid is False
    # Sequence check detects that record 3 is missing expected ID 2
    assert corrupted_id == rec3.id


@pytest.mark.asyncio
async def test_audit_tail_deletion_detection_single_and_multiple(test_db, test_settings):
    """
    Scenario: Verification of 10 audit records, followed by single tail deletion,
    and multiple tail deletions.
    """
    key = b"test_key_1234567890123456789012"
    audit = AuditLogger(test_db, settings=test_settings, key=key)

    # 1. Create 10 audit records
    for i in range(1, 11):
        await audit.log_event("System", f"ACTION_{i}", f"resource_{i}", {"step": i})

    # 2. Verify complete chain (10 records)
    is_valid, err_id = await audit.verify_integrity()
    assert is_valid is True
    assert err_id is None

    # 3. Delete single final record (record 10)
    await test_db.execute_write("DELETE FROM audit_records WHERE id = 10")
    is_valid, err_id = await audit.verify_integrity()
    assert is_valid is False
    assert err_id == 10  # Checkpoint expects ID 10, database ends at ID 9

    # 4. Delete multiple final records (delete records 8, 9)
    await test_db.execute_write("DELETE FROM audit_records WHERE id >= 8")
    is_valid, err_id = await audit.verify_integrity()
    assert is_valid is False
    assert err_id == 10  # Checkpoint still expects ID 10


@pytest.mark.asyncio
async def test_audit_checkpoint_tampering_detection(test_db, test_settings):
    """Detection when external checkpoint file is tampered with or modified."""
    key = b"test_key_1234567890123456789012"
    audit = AuditLogger(test_db, settings=test_settings, key=key)

    for i in range(1, 4):
        await audit.log_event("User", f"ACTION_{i}", "res", {})

    assert (await audit.verify_integrity())[0] is True

    # Tamper with checkpoint JSON content (alter sequence ID without valid HMAC)
    cp_path = audit.checkpoint_path
    cp_data = json.loads(cp_path.read_text(encoding="utf-8"))
    cp_data["last_sequence_id"] = 99
    cp_path.write_text(json.dumps(cp_data), encoding="utf-8")

    is_valid, err_id = await audit.verify_integrity()
    assert is_valid is False
    assert err_id is None


@pytest.mark.asyncio
async def test_audit_checkpoint_interrupted_write_detection(test_db, test_settings):
    """Detection when checkpoint file is empty or corrupted due to an interrupted write."""
    key = b"test_key_1234567890123456789012"
    audit = AuditLogger(test_db, settings=test_settings, key=key)

    await audit.log_event("User", "ACTION_1", "res", {})
    assert (await audit.verify_integrity())[0] is True

    # Simulate zero-byte interrupted write
    audit.checkpoint_path.write_bytes(b"")

    is_valid, err_id = await audit.verify_integrity()
    assert is_valid is False


@pytest.mark.asyncio
async def test_audit_checkpoint_persistence_across_restart(temp_dir, test_settings):
    """Verify that restarting ZORO preserves and validates the checkpoint seamlessly."""
    db_path = temp_dir / "audit_persist.db"
    db1 = DatabaseManager(db_path=db_path, settings=test_settings)
    await db1.initialize()

    key = b"test_key_1234567890123456789012"
    audit1 = AuditLogger(db1, settings=test_settings, key=key)

    for i in range(1, 6):
        await audit1.log_event("User", f"STEP_{i}", "res", {})

    assert (await audit1.verify_integrity())[0] is True
    await db1.close()

    # Reopen in new database and audit instances
    db2 = DatabaseManager(db_path=db_path, settings=test_settings)
    await db2.initialize()
    audit2 = AuditLogger(db2, settings=test_settings, key=key)

    is_valid, err_id = await audit2.verify_integrity()
    assert is_valid is True
    assert err_id is None
    await db2.close()
