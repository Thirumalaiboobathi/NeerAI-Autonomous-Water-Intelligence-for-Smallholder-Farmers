"""Document-style repository: Pydantic entities are stored as JSON under (kind, id, parent).

Two backends implement the same protocol: SQLAlchemy (SQLite locally, PostgreSQL in production) and DynamoDB (AWS).
"""
from __future__ import annotations

from typing import Optional, Protocol, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

FARM, FIELD, EXECUTION, PLAN, SCENARIO = "farm", "field", "execution", "plan", "scenario"


class Repository(Protocol):
    def put(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None) -> None: ...
    def get_raw(self, kind: str, id: str) -> Optional[str]: ...
    def list_raw(self, kind: str, parent: Optional[str] = None, limit: int = 500) -> list[str]: ...
    def delete(self, kind: str, id: str) -> None: ...
    def count(self, kind: str) -> int: ...


class Store:
    """Typed convenience layer over a Repository."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def save(self, kind: str, doc: BaseModel, parent: Optional[str] = None) -> None:
        self.repo.put(kind, doc.id, doc, parent)  # type: ignore[attr-defined]

    def get(self, kind: str, id: str, model: Type[T]) -> Optional[T]:
        raw = self.repo.get_raw(kind, id)
        return model.model_validate_json(raw) if raw else None

    def list(self, kind: str, model: Type[T], parent: Optional[str] = None, limit: int = 500) -> list[T]:
        return [model.model_validate_json(r) for r in self.repo.list_raw(kind, parent, limit)]

    def delete(self, kind: str, id: str) -> None:
        self.repo.delete(kind, id)

    def count(self, kind: str) -> int:
        return self.repo.count(kind)
