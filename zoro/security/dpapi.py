"""Windows Data Protection API (DPAPI) wrapper for local secret protection."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import secrets
from typing import Optional

logger = logging.getLogger(__name__)


class DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def dpapi_protect(plaintext: bytes, description: str = "ZoroSecret") -> bytes:
    """Encrypt data using Windows DPAPI (tied to current Windows user login)."""
    if os.name != "nt":
        return plaintext  # Fallback on non-Windows

    crypt32 = ctypes.WinDLL("Crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    in_blob = DATA_BLOB(
        len(plaintext),
        ctypes.cast(ctypes.create_string_buffer(plaintext), ctypes.POINTER(ctypes.c_byte)),
    )
    out_blob = DATA_BLOB()

    ret = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        description,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ret:
        err = ctypes.get_last_error()
        raise OSError(f"CryptProtectData failed with error {err}")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def dpapi_unprotect(ciphertext: bytes) -> bytes:
    """Decrypt DPAPI-protected data using the current Windows user credentials."""
    if os.name != "nt":
        return ciphertext

    crypt32 = ctypes.WinDLL("Crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    in_blob = DATA_BLOB(
        len(ciphertext),
        ctypes.cast(ctypes.create_string_buffer(ciphertext), ctypes.POINTER(ctypes.c_byte)),
    )
    out_blob = DATA_BLOB()

    ret = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    )
    if not ret:
        err = ctypes.get_last_error()
        raise OSError(f"CryptUnprotectData failed with error {err}")

    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


class AuditKeyManager:
    """Manages creation, DPAPI storage, and retrieval of the HMAC audit secret key."""

    def __init__(self, key_path: Optional[Path] = None) -> None:
        if key_path:
            self.key_path = Path(key_path)
        else:
            from zoro.config.paths import default_paths
            self.key_path = default_paths.security_dir / "audit.key"

    def get_or_create_key(self) -> bytes:
        """Retrieve existing DPAPI-decrypted key, or generate and store a new 32-byte key."""
        if self.key_path.exists():
            try:
                encrypted_bytes = self.key_path.read_bytes()
                return dpapi_unprotect(encrypted_bytes)
            except Exception as e:
                logger.warning("Failed to decrypt existing DPAPI audit key (%s). Generating new key.", e)

        # Generate a fresh 32-byte cryptographically secure random key
        raw_key = secrets.token_bytes(32)
        try:
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            encrypted = dpapi_protect(raw_key, description="ZoroAuditHmacKey")
            self.key_path.write_bytes(encrypted)
            logger.info("Generated new DPAPI-protected audit key at %s", self.key_path)
        except Exception as e:
            logger.error("Failed to write DPAPI audit key: %s. Using in-memory key.", e)

        return raw_key
