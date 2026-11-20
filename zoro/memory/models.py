"""Domain models for PROJECT ZORO Milestone 05: Persistent Personal Memory Architecture."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class MemoryCategory(str, Enum):
    """Five core architectural memory categories."""
    IDENTITY = "IDENTITY"
    PREFERENCE = "PREFERENCE"
    EPISODIC = "EPISODIC"
    PROJECT = "PROJECT"
    SCHEDULE = "SCHEDULE"


class MemorySource(str, Enum):
    """Origin and provenance tracking for stored memories."""
    EXPLICIT_USER = "explicit_user"
    EXTRACTED_CONVERSATION = "extracted_conversation"
    SYSTEM = "system"
    USER_EDIT = "user_edit"


class EventStatus(str, Enum):
    """Status lifecycle for schedule and episodic event items."""
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    IN_PROGRESS = "IN_PROGRESS"
    ARCHIVED = "ARCHIVED"


class MemoryItem(BaseModel):
    """Full representation of a persistent memory entity."""
    id: str
    category: MemoryCategory
    content: str
    summary: Optional[str] = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: MemorySource = MemorySource.EXTRACTED_CONVERSATION
    project_name: Optional[str] = None
    event_timestamp: Optional[str] = None
    event_status: Optional[EventStatus] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    is_deleted: bool = False

    model_config = {"from_attributes": True}


class MemoryCreate(BaseModel):
    """Payload to persist a new memory candidate."""
    category: MemoryCategory
    content: str
    summary: Optional[str] = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: MemorySource = MemorySource.EXTRACTED_CONVERSATION
    project_name: Optional[str] = None
    event_timestamp: Optional[str] = None
    event_status: Optional[EventStatus] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MemoryUpdate(BaseModel):
    """Payload to update an existing memory item."""
    content: Optional[str] = None
    summary: Optional[str] = None
    importance: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    project_name: Optional[str] = None
    event_timestamp: Optional[str] = None
    event_status: Optional[EventStatus] = None
    metadata: Optional[Dict[str, Any]] = None
    source: Optional[MemorySource] = MemorySource.USER_EDIT


class MemoryFilter(BaseModel):
    """Criteria for filtering and querying stored memories."""
    category: Optional[MemoryCategory] = None
    project_name: Optional[str] = None
    include_deleted: bool = False
    source: Optional[MemorySource] = None
    event_status: Optional[EventStatus] = None
    limit: int = 50
    offset: int = 0


class SearchResult(BaseModel):
    """Ranked memory search result combining relevance score and match classification."""
    memory: MemoryItem
    score: float = Field(ge=0.0, le=1.0)
    match_type: str = "semantic"  # "semantic", "keyword", "hybrid"
