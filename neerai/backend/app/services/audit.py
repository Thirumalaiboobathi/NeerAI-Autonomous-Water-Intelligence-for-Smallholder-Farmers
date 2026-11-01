"""Audit/activity trail for critical actions (job submitted, decision generated, plan saved). Ids only, no free text."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..repositories.base import AUDIT, Store
from ..schemas.domain import new_id, now_utc

RETENTION_S = 90 * 86400


class AuditRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("audit"))
    action: str
    ref: str
    at: datetime = Field(default_factory=now_utc)


def record(store: Store, action: str, ref: str) -> None:
    store.save(AUDIT, AuditRecord(action=action, ref=ref), ttl_seconds=RETENTION_S)
