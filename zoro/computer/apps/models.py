"""Application Models for PROJECT ZORO."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class AppInfo:
    """Metadata for an installed or running application."""
    name: str
    display_name: str
    executable_path: Optional[Path] = None
    version: Optional[str] = None
    publisher: Optional[str] = None
    is_running: bool = False
    pid: Optional[int] = None
    main_window_handle: Optional[int] = None
