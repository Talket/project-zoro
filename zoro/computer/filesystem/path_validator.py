"""Path Security Validator for PROJECT ZORO.

Enforces strict path security controls:
- Canonical path resolution
- Directory traversal prevention
- Symbolic link & NTFS directory junction / reparse point escape detection
- Critical security file & system path protection
"""

from __future__ import annotations

import ctypes
import logging
import os
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

# Win32 file attribute flag for reparse point (junction / symlink)
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400

# Critical filenames that must never be modified or deleted by ZORO
PROTECTED_FILENAMES = {
    "audit.key",
    "emergency.lock",
    "zoro.pid",
    "audit.checkpoint",
    "id_rsa",
    "id_ed25519",
}

# Protected system directories on Windows
SYSTEM_DIRECTORY_PATTERNS = [
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\system volume information",
    r"c:\recovery",
    r"c:\boot",
]


class PathSecurityValidator:
    """Validates filesystem paths against security boundaries and constraints."""

    def __init__(self, allowed_roots: Optional[list[Path]] = None) -> None:
        self.allowed_roots = [r.resolve() for r in (allowed_roots or [Path.cwd()])]

    def canonicalize(self, raw_path: Union[str, Path]) -> Path:
        """Resolves path to its canonical, absolute form."""
        p = Path(raw_path)
        return p.resolve()

    def is_reparse_point(self, path: Path) -> bool:
        """Checks if a path on Windows is an NTFS reparse point (junction or symlink)."""
        if os.name != "nt":
            return path.is_symlink()

        try:
            if path.is_symlink():
                return True
            attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
            if attrs == -1 or attrs == 0xFFFFFFFF:
                return False
            return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)
        except Exception:
            return False

    def is_protected_security_path(self, path: Path) -> tuple[bool, str]:
        """Checks if the path touches a critical security file or Windows system path."""
        canon = self.canonicalize(path)
        canon_str = str(canon).lower()

        # 1. Protected filename match
        if canon.name.lower() in PROTECTED_FILENAMES:
            return True, f"Tampering with security-critical file '{canon.name}' is strictly forbidden."

        # 2. Protected system directory match
        for sys_dir in SYSTEM_DIRECTORY_PATTERNS:
            if canon_str == sys_dir or canon_str.startswith(sys_dir + "\\"):
                return True, f"Access to system-critical directory '{sys_dir}' is strictly forbidden."

        # 3. .git directory protection
        if ".git" in canon.parts:
            return True, "Modifying internal version control '.git' directory is forbidden."

        return False, ""

    def validate_path(
        self,
        path: Union[str, Path],
        for_write: bool = False,
        must_exist: bool = False,
    ) -> tuple[bool, str, Optional[Path]]:
        """Performs full path security validation.

        Returns (is_valid, error_message, canonical_path).
        """
        raw_str = str(path)

        # 1. Check for explicit path traversal sequences in raw string
        parts = raw_str.replace("\\", "/").split("/")
        for p in parts:
            if set(p) == {"."} and len(p) > 2:
                return False, f"Illegal path traversal sequence '{p}' is strictly forbidden", None
            if p == "..":
                logger.warning("Directory traversal sequence '..' detected in path: %s", raw_str)

        try:
            canon = self.canonicalize(path)
        except Exception as e:
            return False, f"Invalid path syntax: {e}", None

        # 2. Check existence if required
        if must_exist and not canon.exists():
            return False, f"Path does not exist: {canon}", canon

        # 3. Check protected system and security files
        is_prot, prot_msg = self.is_protected_security_path(canon)
        if is_prot:
            if for_write:
                logger.critical("Security violation blocked: Attempted write/delete to protected path: %s", canon)
                return False, prot_msg, canon
            # For read, allow only if explicitly outside Windows system dirs and not audit keys/locks
            if canon.name.lower() in PROTECTED_FILENAMES:
                return False, prot_msg, canon

        # 4. Check reparse point / symlink escape
        if canon.exists() and self.is_reparse_point(canon):
            try:
                target_resolved = canon.resolve(strict=True)
                # Verify resolved target is not a protected path
                t_prot, t_msg = self.is_protected_security_path(target_resolved)
                if t_prot:
                    return False, f"Symlink/Junction points to protected location: {t_msg}", canon
            except Exception as e:
                return False, f"Failed to resolve reparse point safely: {e}", canon

        # 5. Check allowed roots confinement if configured
        if self.allowed_roots:
            is_under_root = False
            for root in self.allowed_roots:
                try:
                    canon.relative_to(root)
                    is_under_root = True
                    break
                except ValueError:
                    continue
            if not is_under_root:
                return False, f"Path '{canon}' is outside permitted workspace roots: {[str(r) for r in self.allowed_roots]}", canon

        return True, "", canon
