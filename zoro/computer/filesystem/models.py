"""Models for the Secure Filesystem Agent in PROJECT ZORO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class FileRiskTier(str, Enum):
    """Risk tiers for filesystem operations."""
    READ_ONLY = "READ_ONLY"          # Listing directories, reading files
    LOW_RISK = "LOW_RISK"            # Creating new temporary or scratch files
    SENSITIVE = "SENSITIVE"          # Modifying existing user files or configs
    DESTRUCTIVE = "DESTRUCTIVE"      # Deleting files/dirs, overwriting files


@dataclass
class FileInfo:
    """Detailed file and directory metadata."""
    path: Path
    name: str
    size_bytes: int
    is_dir: bool
    is_symlink: bool
    is_reparse_point: bool
    modified_at: datetime
    created_at: datetime
    is_readonly: bool


@dataclass
class FileOperationPreview:
    """Preview of a proposed filesystem operation."""
    operation: str
    source_path: Path
    target_path: Optional[Path] = None
    affected_files_count: int = 1
    total_bytes: int = 0
    risk_tier: FileRiskTier = FileRiskTier.READ_ONLY
    requires_approval: bool = False
    warning: Optional[str] = None


@dataclass
class FileOperationResult:
    """Outcome of a filesystem operation."""
    success: bool
    operation: str
    path: Path
    target_path: Optional[Path] = None
    bytes_processed: int = 0
    error: Optional[str] = None
    recycle_bin: bool = False
