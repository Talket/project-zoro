"""Comprehensive tests for HMAC-SHA256 chained audit logging and DPAPI key management."""

import pytest
from zoro.security.audit import AuditLogger, GENESIS_HASH
from zoro.security.dpapi import AuditKeyManager, dpapi_protect, dpapi_unprotect


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
async def test_audit_modified_entry_detection(test_db, test_settings, temp_dir):
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
async def test_audit_deleted_entry_detection(test_db, test_settings, temp_dir):
    """Detection of deleted audit entries (middle and tail)."""
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
async def test_audit_reordered_entry_detection(test_db, test_settings):
    """Detection of reordered audit entries."""
    key = b"test_key_1234567890123456789012"
    audit = AuditLogger(test_db, settings=test_settings, key=key)

    rec1 = await audit.log_event("User", "ACTION_1", "res1", {})
    rec2 = await audit.log_event("User", "ACTION_2", "res2", {})

    # Swap record 1 and record 2 actions/hashes
    await test_db.execute_write("UPDATE audit_records SET id = 99 WHERE id = 1")
    await test_db.execute_write("UPDATE audit_records SET id = 1 WHERE id = 2")
    await test_db.execute_write("UPDATE audit_records SET id = 2 WHERE id = 99")

    is_valid, corrupted_id = await audit.verify_integrity()
    assert is_valid is False


@pytest.mark.asyncio
async def test_audit_invalid_hmac_detection(test_db, test_settings):
    """Detection when a record has an invalid HMAC signature."""
    key = b"test_key_1234567890123456789012"
    audit = AuditLogger(test_db, settings=test_settings, key=key)

    rec1 = await audit.log_event("User", "ACTION_1", "res1", {})

    # Tamper with record_hash
    await test_db.execute_write("UPDATE audit_records SET record_hash = 'badhash0000000000000000000000000000000000000000000000000000000000' WHERE id = 1")

    is_valid, corrupted_id = await audit.verify_integrity()
    assert is_valid is False
    assert corrupted_id == 1
