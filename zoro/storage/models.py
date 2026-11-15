"""Storage data models and schema definitions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class SystemEvent(BaseModel):
    """Event log record stored in the database."""
    id: Optional[int] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    category: str
    event_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)

    def payload_json(self) -> str:
        return json.dumps(self.payload)


class HealthMetricRecord(BaseModel):
    """Periodic hardware telemetry snapshot."""
    id: Optional[int] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    cpu_percent: float
    ram_used_mb: float
    ram_total_mb: float
    gpu_vram_used_mb: Optional[float] = None
    gpu_vram_total_mb: Optional[float] = None
    gpu_temp_c: Optional[float] = None
    gpu_utilization_percent: Optional[float] = None
    disk_free_gb: float


class AuditRecord(BaseModel):
    """Tamper-evident cryptographically chained audit record."""
    id: Optional[int] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    actor: str
    action: str
    resource: str
    details: Dict[str, Any] = Field(default_factory=dict)
    prev_hash: str
    record_hash: str

    def details_json(self) -> str:
        return json.dumps(self.details)


class ConfigEntry(BaseModel):
    """Dynamic key-value configuration entry."""
    key: str
    value: str
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
