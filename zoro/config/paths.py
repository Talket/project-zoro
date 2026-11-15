"""Filesystem path resolution and environment directory management."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class AppPaths:
    """Centralized path manager for PROJECT ZORO."""

    def __init__(self, custom_data_dir: Optional[Path | str] = None) -> None:
        # Determine project workspace root (repository root)
        self.workspace_root: Path = Path(__file__).resolve().parent.parent.parent

        # User data root: default to %APPDATA%/Zoro on Windows, ~/.zoro on others
        if custom_data_dir:
            self.data_dir: Path = Path(custom_data_dir).resolve()
        elif "ZORO_DATA_DIR" in os.environ:
            self.data_dir = Path(os.environ["ZORO_DATA_DIR"]).resolve()
        elif os.name == "nt":
            appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
            self.data_dir = Path(appdata) / "Zoro"
        else:
            self.data_dir = Path.home() / ".zoro"

        # Security directory: %PROGRAMDATA%/Zoro/Security or fallback to data_dir/Security
        if "ZORO_SECURITY_DIR" in os.environ:
            self.security_dir: Path = Path(os.environ["ZORO_SECURITY_DIR"]).resolve()
        elif os.name == "nt":
            programdata = os.environ.get("ProgramData", "C:\\ProgramData")
            self.security_dir = Path(programdata) / "Zoro" / "Security"
        else:
            self.security_dir = self.data_dir / "security"

        # Sub-paths
        self.logs_dir: Path = self.data_dir / "logs"
        self.db_path: Path = self.data_dir / "zoro.db"
        self.halt_lock_path: Path = self.security_dir / "halt.lock"
        self.pid_path: Path = self.data_dir / "zoro.pid"
        self.audit_checkpoint_path: Path = self.security_dir / "audit.checkpoint"
        self.ipc_pipe_name: str = os.environ.get("ZORO_PIPE_NAME", r"\\.\pipe\zoro-ipc-main")

    def ensure_directories(self) -> None:
        """Create required application directories if they do not exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.security_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError):
            # Fallback if non-admin cannot create in ProgramData
            fallback_sec = self.data_dir / "security"
            fallback_sec.mkdir(parents=True, exist_ok=True)
            self.security_dir = fallback_sec
            self.halt_lock_path = self.security_dir / "halt.lock"
            self.audit_checkpoint_path = self.security_dir / "audit.checkpoint"


# Global singleton instance
default_paths = AppPaths()
