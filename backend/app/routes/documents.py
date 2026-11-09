from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.base import AiError, AiUnavailable
from app.config import get_settings
from app.db import get_db
from app.domain.extraction import FIELDS
from app.errors import ApiError, not_found
from app.models import DocStatus, Document, Page, QaEntry
from app.ratelimit import limiter
from app.security import CurrentUser
from app.services import jobs, qa
from app.services.files import validate_upload

router = APIRouter(prefix="/api/documents", tags=["documents"])
Db = Annotated[Session, Depends(get_db)]


def _owned(db: Session, user_id: str, doc_id: str) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.user_id != user_id:  # someone else's document looks exactly like a missing one
        raise not_found("Document")
    return doc


def _summary(d: Document) -> dict:
    return {
        "id": d.id,
        "filename": d.filename,
        "status": d.status.value,
        "error": d.error,
        "doc_type": d.doc_type.value if d.doc_type else None,
        "language": d.language,
        "page_count": d.page_count,
        "pii_counts": d.pii_counts or {},
        "text_source": d.text_source,
        "original_deleted": d.original_deleted,
        "is_demo": d.is_demo,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


@router.post("", status_code=202)
async def upload(
    user: CurrentUser,
    db: Db,
    file: Annotated[UploadFile, File()],
    language: Annotated[Literal["en-IN", "hi-IN"], Form()] = "hi-IN",
) -> dict:
    s = get_settings()
    limiter.hit("upload", user.id, s.upload_per_hour)
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)  # never read more than the limit + 1 byte
    info = validate_upload(data, s.max_upload_mb, s.max_pages)
    existing = db.scalar(select(Document).where(Document.user_id == user.id, Document.sha256 == info.sha256))
    if existing:
        raise ApiError(409, "duplicate", "You have already uploaded this file", {"document_id": existing.id})
    doc = Document(
        user_id=user.id,
        filename=(file.filename or "document")[:255],
        content_type=info.content_type,
        size_bytes=len(data),
        sha256=info.sha256,
        language=language,
        page_count=info.page_count,
    )
    db.add(doc)
    db.flush()
    jobs.enqueue(db, doc.id, data)
    db.commit()
    return _summary(doc)


@router.get("")
def list_documents(user: CurrentUser, db: Db) -> dict:
    docs = db.scalars(select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())).all()
    return {"items": [_summary(d) for d in docs]}


@router.get("/{doc_id}")
def get_document(doc_id: str, user: CurrentUser, db: Db) -> dict:
    d = _owned(db, user.id, doc_id)
    fields = dict(d.fields or {})
    meta = fields.pop("_meta", None)
    labels = FIELDS.get(d.doc_type, {}) if d.doc_type else {}
    # JSONB does not keep key order, so return fields in the order the schema defines them.
    order = [k for k in labels if k in fields] + [k for k in fields if k not in labels]
    return {
        **_summary(d),
        "meta": meta,
        "fields": [
            {"name": k, "label_en": labels.get(k, (k, k))[0], "label_hi": labels.get(k, (k, k))[1], **fields[k]} for k in order
        ],
    }


@router.get("/{doc_id}/pages")
def get_pages(doc_id: str, user: CurrentUser, db: Db) -> dict:
    d = _owned(db, user.id, doc_id)
    pages = db.scalars(select(Page).where(Page.document_id == d.id).order_by(Page.page_number)).all()
    return {"pages": [{"page": p.page_number, "text": p.masked_text} for p in pages]}


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=500)


@router.post("/{doc_id}/ask")
def ask(doc_id: str, body: AskIn, user: CurrentUser, db: Db) -> dict:
    d = _owned(db, user.id, doc_id)
    if d.status != DocStatus.ready:
        raise ApiError(409, "not_ready", "This document is still being processed")
    limiter.hit("ask", user.id, get_settings().ask_per_hour)
    try:
        r = qa.ask(db, user, d, body.question.strip())
    except AiUnavailable as e:
        raise ApiError(503, "ai_unavailable", str(e)) from e
    except AiError as e:
        raise ApiError(502, "ai_error", "The AI service could not answer right now. Please try again.") from e
    return {
        "answer": r.answer,
        "language": r.language,
        "citations": r.citations,
        "refused": r.refused,
        "sources": r.sources,
        "latency_ms": r.latency_ms,
        "demo_mode": r.demo_mode,
    }


@router.get("/{doc_id}/history")
def history(doc_id: str, user: CurrentUser, db: Db) -> dict:
    d = _owned(db, user.id, doc_id)
    rows = db.scalars(select(QaEntry).where(QaEntry.document_id == d.id).order_by(QaEntry.created_at)).all()
    return {
        "items": [
            {
                "id": q.id,
                "question": q.question,
                "answer": q.answer,
                "language": q.language,
                "citations": q.citations,
                "refused": q.refused,
                "created_at": q.created_at.isoformat(),
            }
            for q in rows
        ]
    }


@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: str, user: CurrentUser, db: Db) -> Response:
    d = _owned(db, user.id, doc_id)
    db.delete(d)
    db.commit()
    return Response(status_code=204)
