"""Async agent job records. Lifecycle: queued -> running -> succeeded | failed (a retry puts a running job back to queued)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from .domain import Language, new_id, now_utc

JobStatus = Literal["queued", "running", "succeeded", "failed"]
TERMINAL: set[str] = {"succeeded", "failed"}


class JobRequest(BaseModel):
    """What the worker needs to run one agent workflow. Contains the farmer's question, hence the short job TTL."""

    kind: Literal["assess", "chat"] = "assess"
    farm_id: str
    query: str = Field(min_length=1, max_length=500)
    language: Language = Language.en
    available_litres: Optional[float] = Field(default=None, ge=0, le=1e10)
    priority_overrides: dict[str, float] = Field(default_factory=dict)
    weather_scenario: Optional[str] = None


class JobError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class Job(BaseModel):
    id: str = Field(default_factory=lambda: new_id("job"))
    status: JobStatus = "queued"
    version: int = 0  # optimistic-locking counter used for conditional state transitions
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
    attempts: int = 0
    progress: str = "queued"
    request: JobRequest
    execution_id: Optional[str] = None
    error: Optional[JobError] = None
    correlation_id: str = "-"
    metrics: dict[str, Any] = Field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL


class JobView(BaseModel):
    """Public shape returned by the API (no internal counters or the raw request)."""

    id: str
    status: JobStatus
    progress: str
    created_at: datetime
    updated_at: datetime
    attempts: int
    execution_id: Optional[str] = None
    error: Optional[JobError] = None
    kind: str
    farm_id: str

    @classmethod
    def of(cls, j: Job) -> "JobView":
        return cls(id=j.id, status=j.status, progress=j.progress, created_at=j.created_at, updated_at=j.updated_at,
                   attempts=j.attempts, execution_id=j.execution_id, error=j.error, kind=j.request.kind, farm_id=j.request.farm_id)
