"""Document-style repository: Pydantic entities are stored as JSON under (owner, kind, id, parent).

Every record belongs to exactly one owner (the authenticated user id; "local" when auth is off). The owner is part of the
storage key, so a request authenticated as user A cannot address user B's records at all (structural IDOR protection).

Two backends implement the same protocol: SQLAlchemy (SQLite locally, PostgreSQL optional) and DynamoDB (AWS).
"""
from __future__ import annotations

from typing import Optional, Protocol, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

FARM, FIELD, EXECUTION, PLAN, SCENARIO, JOB, AUDIT = "farm", "field", "execution", "plan", "scenario", "job", "audit"
LOCAL_OWNER = "local"


class Repository(Protocol):
    def put(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None, *, owner: str = LOCAL_OWNER,
            ttl_seconds: Optional[int] = None) -> None: ...
    def put_conditional(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None, *, owner: str = LOCAL_OWNER,
                        ttl_seconds: Optional[int] = None, if_absent: bool = False, expect_version: Optional[int] = None) -> bool: ...
    def get_raw(self, kind: str, id: str, *, owner: str = LOCAL_OWNER) -> Optional[str]: ...
    def list_raw(self, kind: str, parent: Optional[str] = None, limit: int = 500, *, owner: str = LOCAL_OWNER) -> list[str]: ...
    def delete(self, kind: str, id: str, *, owner: str = LOCAL_OWNER) -> None: ...
    def count(self, kind: str, *, owner: str = LOCAL_OWNER) -> int: ...


class Store:
    """Typed convenience layer over a Repository, bound to one owner."""

    def __init__(self, repo: Repository, owner: str = LOCAL_OWNER):
        self.repo = repo
        self.owner = owner

    def scoped(self, owner: str) -> "Store":
        return Store(self.repo, owner)

    def save(self, kind: str, doc: BaseModel, parent: Optional[str] = None, ttl_seconds: Optional[int] = None) -> None:
        self.repo.put(kind, doc.id, doc, parent, owner=self.owner, ttl_seconds=ttl_seconds)  # type: ignore[attr-defined]

    def save_conditional(self, kind: str, doc: BaseModel, parent: Optional[str] = None, ttl_seconds: Optional[int] = None,
                         if_absent: bool = False, expect_version: Optional[int] = None) -> bool:
        return self.repo.put_conditional(kind, doc.id, doc, parent, owner=self.owner, ttl_seconds=ttl_seconds,  # type: ignore[attr-defined]
                                         if_absent=if_absent, expect_version=expect_version)

    def get(self, kind: str, id: str, model: Type[T]) -> Optional[T]:
        raw = self.repo.get_raw(kind, id, owner=self.owner)
        return model.model_validate_json(raw) if raw else None

    def list(self, kind: str, model: Type[T], parent: Optional[str] = None, limit: int = 500) -> list[T]:
        return [model.model_validate_json(r) for r in self.repo.list_raw(kind, parent, limit, owner=self.owner)]

    def delete(self, kind: str, id: str) -> None:
        self.repo.delete(kind, id, owner=self.owner)

    def count(self, kind: str) -> int:
        return self.repo.count(kind, owner=self.owner)
