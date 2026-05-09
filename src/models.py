from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


JsonObject = dict[str, Any]


class TurnMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "tool", "system"]
    content: str = Field(min_length=0, max_length=50_000)
    name: str | None = Field(default=None, max_length=256)


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=512)
    user_id: str | None = Field(default=None, max_length=512)
    messages: list[TurnMessage] = Field(min_length=1, max_length=100)
    timestamp: datetime
    metadata: JsonObject = Field(default_factory=dict)


class TurnResponse(BaseModel):
    id: str


class Citation(BaseModel):
    turn_id: str
    score: float
    snippet: str


class RecallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=10_000)
    session_id: str = Field(min_length=1, max_length=512)
    user_id: str | None = Field(default=None, max_length=512)
    max_tokens: int = Field(default=1024, ge=1, le=16_384)


class RecallResponse(BaseModel):
    context: str
    citations: list[Citation]


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=10_000)
    session_id: str | None = Field(default=None, max_length=512)
    user_id: str | None = Field(default=None, max_length=512)
    limit: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    content: str
    score: float
    session_id: str
    timestamp: str
    metadata: JsonObject


class SearchResponse(BaseModel):
    results: list[SearchResult]


class MemoryView(BaseModel):
    id: str
    type: Literal["fact", "preference", "opinion", "event"]
    key: str
    value: str
    confidence: float
    source_session: str
    source_turn: str
    created_at: str
    updated_at: str
    supersedes: str | None
    active: bool


class UserMemoriesResponse(BaseModel):
    memories: list[MemoryView]
