"""Database models (SQLAlchemy 2, typed). Only masked text is ever stored; original files are deleted."""

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

JsonType = JSON().with_variant(JSONB(), "postgresql")


def _now() -> datetime:
    return datetime.now(UTC)


def _uuid() -> str:
    return str(uuid.uuid4())


class DocStatus(enum.StrEnum):
    queued = "queued"
    reading = "reading"
    masking = "masking"
    extracting = "extracting"
    ready = "ready"
    failed = "failed"


class DocType(enum.StrEnum):
    rent_agreement = "rent_agreement"
    electricity_bill = "electricity_bill"
    bank_statement = "bank_statement"
    property_record = "property_record"
    other = "other"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(100))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("user_id", "sha256", name="uq_document_user_hash"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(10), default="en-IN")  # the language the user picked
    status: Mapped[DocStatus] = mapped_column(Enum(DocStatus, name="doc_status"), default=DocStatus.queued, index=True)
    error: Mapped[str | None] = mapped_column(Text)  # user-readable failure message
    page_count: Mapped[int | None] = mapped_column(Integer)
    text_source: Mapped[str | None] = mapped_column(String(20))  # "pdf_text" | "ocr"
    doc_type: Mapped[DocType | None] = mapped_column(Enum(DocType, name="doc_type"))
    # {"AADHAAR": 1, "PHONE": 2}: counts only, never the values.
    pii_counts: Mapped[dict] = mapped_column(JsonType, default=dict)
    # {"monthly_rent": {"value": 12000, "page": 1, "confidence": "high"}, ...}
    fields: Mapped[dict] = mapped_column(JsonType, default=dict)
    original_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    pages: Mapped[list["Page"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Page.page_number"
    )


class Page(Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("document_id", "page_number", name="uq_page_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    masked_text: Mapped[str] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="pages")


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    page: Mapped[int] = mapped_column(Integer)
    idx: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # 'simple' config: no stemming, splits on whitespace/punctuation, so Devanagari words are kept intact.
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True))


class Job(Base):
    """One processing job per upload. Claimed with SELECT ... FOR UPDATE SKIP LOCKED (see services/jobs.py)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_claim", "status", "run_after"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="job_status"), default=JobStatus.queued)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class QaEntry(Base):
    """Question/answer history per document."""

    __tablename__ = "qa_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10))
    citations: Mapped[list] = mapped_column(JsonType, default=list)  # [2, 3]
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
