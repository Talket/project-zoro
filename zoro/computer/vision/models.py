"""Vision and Screen Models for PROJECT ZORO."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class ScreenRegion:
    """Bounding rectangle for a specific screen region."""
    left: int
    top: int
    width: int
    height: int
    monitor_idx: int = 0

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


@dataclass
class CaptureResult:
    """Result of a screen capture operation."""
    image_path: Path
    width: int
    height: int
    monitor_idx: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    file_size_bytes: int = 0


@dataclass
class OCRWord:
    """Individual word identified by OCR with bounding box."""
    text: str
    x: float
    y: float
    width: float
    height: float
    confidence: float = 1.0


@dataclass
class OCRResult:
    """Full OCR outcome."""
    full_text: str
    words: list[OCRWord] = field(default_factory=list)
    language: str = "en-US"
    success: bool = True
    error: Optional[str] = None
