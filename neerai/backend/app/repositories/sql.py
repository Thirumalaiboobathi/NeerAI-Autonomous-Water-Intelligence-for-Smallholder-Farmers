"""SQLAlchemy repository (SQLite for local dev; any SQLAlchemy URL such as PostgreSQL for production)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel
from sqlalchemy import DateTime, Index, String, Text, create_engine, delete, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    kind: Mapped[str] = mapped_column(String(24), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    parent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    body: Mapped[str] = mapped_column(Text)
    __table_args__ = (Index("ix_documents_kind_parent", "kind", "parent"),)


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

    def put(self, kind: str, id: str, doc: BaseModel, parent: Optional[str] = None) -> None:
        body = doc.model_dump_json()
        with self._session() as s, s.begin():
            row = s.get(Document, (kind, id))
            if row:
                row.body, row.parent = body, parent
            else:
                s.add(Document(kind=kind, id=id, parent=parent, body=body))

    def get_raw(self, kind: str, id: str) -> Optional[str]:
        with self._session() as s:
            row = s.get(Document, (kind, id))
            return row.body if row else None

    def list_raw(self, kind: str, parent: Optional[str] = None, limit: int = 500) -> list[str]:
        q = select(Document.body).where(Document.kind == kind)
        if parent is not None:
            q = q.where(Document.parent == parent)
        q = q.order_by(Document.created_at.desc()).limit(limit)
        with self._session() as s:
            return list(s.scalars(q))

    def delete(self, kind: str, id: str) -> None:
        with self._session() as s, s.begin():
            s.execute(delete(Document).where(Document.kind == kind, Document.id == id))

    def count(self, kind: str) -> int:
        with self._session() as s:
            return s.scalar(select(func.count()).select_from(Document).where(Document.kind == kind)) or 0
