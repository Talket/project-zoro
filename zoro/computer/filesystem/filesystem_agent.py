"""Secure Filesystem Agent for PROJECT ZORO.

Executes safe, permission-checked filesystem operations on Windows:
- Directory traversal & symlink/junction escape prevention
- Hard protection of security-critical keys and locks
- 50 MB read limits to prevent OOM
- Structured previews for destructive operations
- Reversible deletion via Windows Recycle Bin (SHFileOperationW)
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from zoro.computer.filesystem.models import (
    FileInfo,
    FileOperationPreview,
    FileOperationResult,
    FileRiskTier,
)
from zoro.computer.filesystem.path_validator import PathSecurityValidator

logger = logging.getLogger(__name__)

# Win32 Shell API structures for Recycle Bin operations
class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]

FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400


class SecureFilesystemAgent:
    """Manages all filesystem operations with strict security enforcement."""

    def __init__(
        self,
        validator: Optional[PathSecurityValidator] = None,
        max_read_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self.validator = validator or PathSecurityValidator()
        self.max_read_bytes = max_read_bytes

    def list_dir(self, dir_path: Union[str, Path], max_items: int = 1000) -> list[FileInfo]:
        """Lists files and directories within dir_path with security validation."""
        is_valid, msg, canon = self.validator.validate_path(dir_path, for_write=False, must_exist=True)
        if not is_valid or canon is None:
            raise PermissionError(f"Directory listing blocked: {msg}")

        if not canon.is_dir():
            raise NotADirectoryError(f"Path is not a directory: {canon}")

        results: list[FileInfo] = []
        try:
            with os.scandir(canon) as entries:
                for entry in entries:
                    if len(results) >= max_items:
                        break
                    try:
                        stat = entry.stat(follow_symlinks=False)
                        p = Path(entry.path)
                        is_reparse = self.validator.is_reparse_point(p)
                        results.append(
                            FileInfo(
                                path=p,
                                name=entry.name,
                                size_bytes=stat.st_size if not entry.is_dir() else 0,
                                is_dir=entry.is_dir(follow_symlinks=False),
                                is_symlink=entry.is_symlink(),
                                is_reparse_point=is_reparse,
                                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                                created_at=datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc),
                                is_readonly=bool(stat.st_mode & 0o222 == 0),
                            )
                        )
                    except Exception as e:
                        logger.debug("Failed to read metadata for %s: %s", entry.name, e)
                        continue
        except Exception as e:
            logger.error("Failed to list directory %s: %s", canon, e)
            raise

        return results

    def read_file(
        self,
        path: Union[str, Path],
        max_bytes: Optional[int] = None,
        encoding: str = "utf-8",
    ) -> str:
        """Reads content from a text file up to max_bytes ceiling."""
        raw_bytes = self.read_bytes(path, max_bytes=max_bytes)
        return raw_bytes.decode(encoding, errors="replace")

    def read_bytes(
        self,
        path: Union[str, Path],
        max_bytes: Optional[int] = None,
    ) -> bytes:
        """Reads raw bytes from a file with size limit enforcement."""
        limit = max_bytes or self.max_read_bytes
        is_valid, msg, canon = self.validator.validate_path(path, for_write=False, must_exist=True)
        if not is_valid or canon is None:
            raise PermissionError(f"File read blocked: {msg}")

        if not canon.is_file():
            raise IsADirectoryError(f"Target is not a regular file: {canon}")

        file_size = canon.stat().st_size
        if file_size > limit:
            raise ValueError(
                f"File size ({file_size} bytes) exceeds maximum permitted read limit ({limit} bytes)"
            )

        with open(canon, "rb") as f:
            return f.read(limit)

    def write_file(
        self,
        path: Union[str, Path],
        content: Union[str, bytes],
        overwrite: bool = True,
        encoding: str = "utf-8",
    ) -> FileOperationResult:
        """Writes content to a file safely."""
        is_valid, msg, canon = self.validator.validate_path(path, for_write=True, must_exist=False)
        if not is_valid or canon is None:
            return FileOperationResult(
                success=False,
                operation="write",
                path=Path(path),
                error=msg,
            )

        if canon.exists() and not overwrite:
            return FileOperationResult(
                success=False,
                operation="write",
                path=canon,
                error=f"File already exists and overwrite is disabled: {canon}",
            )

        try:
            canon.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, str):
                data = content.encode(encoding)
            else:
                data = content

            with open(canon, "wb") as f:
                f.write(data)

            return FileOperationResult(
                success=True,
                operation="write",
                path=canon,
                bytes_processed=len(data),
            )
        except Exception as e:
            logger.error("Failed to write to file %s: %s", canon, e)
            return FileOperationResult(
                success=False,
                operation="write",
                path=canon,
                error=str(e),
            )

    def copy_file(self, src: Union[str, Path], dest: Union[str, Path]) -> FileOperationResult:
        """Copies a file from src to dest with security validation."""
        s_valid, s_msg, s_canon = self.validator.validate_path(src, for_write=False, must_exist=True)
        if not s_valid or s_canon is None:
            return FileOperationResult(success=False, operation="copy", path=Path(src), error=s_msg)

        d_valid, d_msg, d_canon = self.validator.validate_path(dest, for_write=True, must_exist=False)
        if not d_valid or d_canon is None:
            return FileOperationResult(success=False, operation="copy", path=s_canon, target_path=Path(dest), error=d_msg)

        try:
            d_canon.parent.mkdir(parents=True, exist_ok=True)
            if s_canon.is_dir():
                shutil.copytree(s_canon, d_canon, dirs_exist_ok=True)
                size = sum(f.stat().st_size for f in d_canon.rglob("*") if f.is_file())
            else:
                shutil.copy2(s_canon, d_canon)
                size = d_canon.stat().st_size

            return FileOperationResult(
                success=True,
                operation="copy",
                path=s_canon,
                target_path=d_canon,
                bytes_processed=size,
            )
        except Exception as e:
            logger.error("Failed to copy %s -> %s: %s", s_canon, d_canon, e)
            return FileOperationResult(
                success=False,
                operation="copy",
                path=s_canon,
                target_path=d_canon,
                error=str(e),
            )

    def move_file(self, src: Union[str, Path], dest: Union[str, Path]) -> FileOperationResult:
        """Moves a file or directory from src to dest with security validation."""
        s_valid, s_msg, s_canon = self.validator.validate_path(src, for_write=True, must_exist=True)
        if not s_valid or s_canon is None:
            return FileOperationResult(success=False, operation="move", path=Path(src), error=s_msg)

        d_valid, d_msg, d_canon = self.validator.validate_path(dest, for_write=True, must_exist=False)
        if not d_valid or d_canon is None:
            return FileOperationResult(success=False, operation="move", path=s_canon, target_path=Path(dest), error=d_msg)

        try:
            d_canon.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(s_canon), str(d_canon))
            return FileOperationResult(
                success=True,
                operation="move",
                path=s_canon,
                target_path=d_canon,
            )
        except Exception as e:
            logger.error("Failed to move %s -> %s: %s", s_canon, d_canon, e)
            return FileOperationResult(
                success=False,
                operation="move",
                path=s_canon,
                target_path=d_canon,
                error=str(e),
            )

    def delete_file(self, path: Union[str, Path], to_recycle_bin: bool = True) -> FileOperationResult:
        """Deletes a file or directory, optionally sending to Windows Recycle Bin."""
        is_valid, msg, canon = self.validator.validate_path(path, for_write=True, must_exist=True)
        if not is_valid or canon is None:
            return FileOperationResult(
                success=False,
                operation="delete",
                path=Path(path),
                error=msg,
            )

        if to_recycle_bin and os.name == "nt":
            try:
                # Windows Recycle Bin via SHFileOperationW
                double_null_path = str(canon) + "\0\0"
                op = SHFILEOPSTRUCTW()
                op.wFunc = FO_DELETE
                op.pFrom = double_null_path
                op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
                ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
                if ret == 0:
                    return FileOperationResult(
                        success=True,
                        operation="delete",
                        path=canon,
                        recycle_bin=True,
                    )
                logger.warning("SHFileOperationW returned code %d, falling back to permanent delete", ret)
            except Exception as e_sh:
                logger.warning("Recycle bin delete failed: %s, falling back to permanent delete", e_sh)

        # Permanent deletion fallback
        try:
            if canon.is_dir():
                shutil.rmtree(canon)
            else:
                canon.unlink()
            return FileOperationResult(
                success=True,
                operation="delete",
                path=canon,
                recycle_bin=False,
            )
        except Exception as e:
            logger.error("Failed to delete %s: %s", canon, e)
            return FileOperationResult(
                success=False,
                operation="delete",
                path=canon,
                error=str(e),
            )

    def preview_operation(
        self,
        op: str,
        src: Union[str, Path],
        dest: Optional[Union[str, Path]] = None,
    ) -> FileOperationPreview:
        """Generates a structured preview of a proposed filesystem operation."""
        s_path = Path(src)
        d_path = Path(dest) if dest else None

        if op == "delete":
            risk = FileRiskTier.DESTRUCTIVE
            count = 1
            bytes_total = 0
            if s_path.exists():
                if s_path.is_dir():
                    files = list(s_path.rglob("*"))
                    count = len(files) + 1
                    bytes_total = sum(f.stat().st_size for f in files if f.is_file())
                else:
                    bytes_total = s_path.stat().st_size

            return FileOperationPreview(
                operation="delete",
                source_path=s_path,
                target_path=None,
                affected_files_count=count,
                total_bytes=bytes_total,
                risk_tier=risk,
                requires_approval=True,
                warning=f"Destructive operation: {count} files/directories ({bytes_total} bytes) will be deleted",
            )

        if op in ("write", "move"):
            risk = FileRiskTier.SENSITIVE if (d_path and d_path.exists()) or s_path.exists() else FileRiskTier.LOW_RISK
            return FileOperationPreview(
                operation=op,
                source_path=s_path,
                target_path=d_path,
                affected_files_count=1,
                risk_tier=risk,
                requires_approval=(risk == FileRiskTier.SENSITIVE),
            )

        return FileOperationPreview(
            operation=op,
            source_path=s_path,
            target_path=d_path,
            affected_files_count=1,
            risk_tier=FileRiskTier.READ_ONLY,
            requires_approval=False,
        )
