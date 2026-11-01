"""SQLAlchemy repository (SQLite for local dev; any SQLAlchemy URL such as PostgreSQL also works).

Schema versioning: table `documents_v2` has the owner in its primary key. The v1 table (`documents`, no owner) is left
untouched and ignored, so upgrading never deletes or rewrites existing local data.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import DateTime, Index, Integer, String, Text, create_engine, delete, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

LOCAL_OWNER = "local"


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents_v2"
    owner: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    parent: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    body: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("ix_documents_v2_owner_kind_parent", "owner", "kind", "parent"),)


def _version(doc: BaseModel) -> int:
    return int(getattr(doc, "version", 0) or 0)


class SqlRepository:
    def __init__(self, url: str = "sqlite:///./neerai.db"):
        kwargs: dict = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url or url.endswith("sqlite://"):
                kwargs["poolclass"] = StaticPool
        self.engine = create_engine(url, future=True, **kwargs)
        Base.metadata.create_all(self.engine)
        self._session = sessionmaker(self.engine, expire_on_commit=False)

    @staticmethod
    def _expiry(ttl_seconds: Optional[int]) -> Optional[int]:
        return int(time.time()) + ttl_seconds if ttl_seconds else None

    def put(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None, *, owner: str = LOCAL_OWNER,
            ttl_seconds: Optional[int] = None) -> None:
        self.put_conditional(kind, id, doc, parent, owner=owner, ttl_seconds=ttl_seconds)

    def put_conditional(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None, *, owner: str = LOCAL_OWNER,
                        ttl_seconds: Optional[int] = None, if_absent: bool = False, expect_version: Optional[int] = None) -> bool:
        """Write the document; returns False (and writes nothing) if a condition fails.

        `if_absent`: only create. `expect_version`: only overwrite if the stored version equals it (optimistic locking).
        """
        body = doc.model_dump_json()
        with self._session() as s, s.begin():
            row = s.get(Document, (owner, kind, id))
            if row is not None and self._expired(row):
                s.delete(row)
                s.flush()
                row = None
            if if_absent and row is not None:
                return False
            if expect_version is not None and (row is None or row.version != expect_version):
                return False
            if row:
                row.body, row.parent, row.version, row.expires_at = body, parent, _version(doc), self._expiry(ttl_seconds) or row.expires_at
            else:
                s.add(Document(owner=owner, kind=kind, id=id, parent=parent, body=body, version=_version(doc),
                               expires_at=self._expiry(ttl_seconds)))
        return True

    @staticmethod
    def _expired(row: Document) -> bool:
        return row.expires_at is not None and row.expires_at < time.time()

    def get_raw(self, kind: str, id: str, *, owner: str = LOCAL_OWNER) -> Optional[str]:
        with self._session() as s:
            row = s.get(Document, (owner, kind, id))
            return row.body if row and not self._expired(row) else None

    def list_raw(self, kind: str, parent: Optional[str] = None, limit: int = 500, *, owner: str = LOCAL_OWNER) -> list[str]:
        q = select(Document).where(Document.owner == owner, Document.kind == kind)
        if parent is not None:
            q = q.where(Document.parent == parent)
        q = q.order_by(Document.created_at.desc()).limit(limit)
        with self._session() as s:
            return [r.body for r in s.scalars(q) if not self._expired(r)]

    def delete(self, kind: str, id: str, *, owner: str = LOCAL_OWNER) -> None:
        with self._session() as s, s.begin():
            s.execute(delete(Document).where(Document.owner == owner, Document.kind == kind, Document.id == id))

    def count(self, kind: str, *, owner: str = LOCAL_OWNER) -> int:
        q = select(func.count()).select_from(Document).where(Document.owner == owner, Document.kind == kind)
        with self._session() as s:
            return s.scalar(q) or 0
