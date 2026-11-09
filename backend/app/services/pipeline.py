"""Document processing: read text -> mask PII -> chunk -> classify + extract fields -> ready.

The document status is committed at each step so the UI can show live progress. Only masked text is stored,
and the original file (held in the job row) is deleted when processing ends, successfully or not.
"""

import json
import logging

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.ai import get_provider
from app.ai.base import AiError, AiUnavailable, Usage, complete_json
from app.ai.prompts import CLASSIFY_SYSTEM, extract_system, extract_user, pages_payload
from app.config import get_settings
from app.domain.chunker import chunk_pages
from app.domain.extraction import Classification, clean_fields, extraction_model
from app.domain.pii import mask_pii
from app.models import Chunk, DocStatus, Document, Job, Page
from app.services import jobs
from app.services.demo_data import DEMO_DIR
from app.services.files import has_usable_text_layer, pdf_text_pages

log = logging.getLogger("kaagaz.pipeline")


class PipelineError(Exception):
    """A failure with a message that is safe and useful to show the user."""


def _set_status(db: Session, doc: Document, status: DocStatus) -> None:
    doc.status = status
    db.commit()


def read_text(doc: Document, data: bytes) -> tuple[list[tuple[int, str]], str]:
    s = get_settings()
    if doc.is_demo:
        # Seeded sample documents ship with their page text prepared in advance (see scripts/make_demo_docs.py).
        sidecar = DEMO_DIR / doc.filename.replace(".pdf", ".pages.json")
        if sidecar.exists():
            pages = json.loads(sidecar.read_text(encoding="utf-8"))["pages"]
            return [(p["page"], p["text"]) for p in pages], "demo_prepared"
    if doc.content_type == "application/pdf":
        pages = pdf_text_pages(data)
        if has_usable_text_layer(pages, s.min_text_chars_per_page):
            return pages, "pdf_text"
    ocr = get_provider().parse_document(data, doc.filename, doc.language)
    pages = [(p.page, p.text) for p in ocr if p.text.strip()]
    if not pages:
        raise PipelineError("No readable text was found in this file.")
    return pages, "ocr"


def process_document(db: Session, doc: Document, data: bytes) -> None:
    provider = get_provider()
    usage = Usage()

    _set_status(db, doc, DocStatus.reading)
    raw_pages, source = read_text(doc, data)

    _set_status(db, doc, DocStatus.masking)
    masked_pages: list[tuple[int, str]] = []
    counts: dict[str, int] = {}
    for n, text in raw_pages:
        r = mask_pii(text)
        masked_pages.append((n, r.text))
        for k, v in r.counts.items():
            counts[k] = counts.get(k, 0) + v
    del raw_pages  # unmasked text is not kept past this point

    # Re-processing replaces earlier rows.
    db.execute(delete(Page).where(Page.document_id == doc.id))
    db.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    db.add_all(Page(document_id=doc.id, page_number=n, masked_text=t) for n, t in masked_pages)
    db.add_all(Chunk(document_id=doc.id, page=c.page, idx=c.index, text=c.text) for c in chunk_pages(masked_pages))
    doc.pii_counts = counts
    doc.text_source = source
    doc.page_count = len(masked_pages)

    _set_status(db, doc, DocStatus.extracting)
    cls = complete_json(provider, "classify", CLASSIFY_SYSTEM, pages_payload(masked_pages), Classification, usage)
    model_cls = extraction_model(cls.doc_type)
    raw = complete_json(
        provider,
        f"extract_{cls.doc_type.value}",
        extract_system(cls.doc_type),
        extract_user(cls.doc_type, masked_pages),
        model_cls,
        usage,
    )
    doc.doc_type = cls.doc_type
    doc.fields = {
        "_meta": {
            "summary": cls.summary,
            "language": cls.language,
            "classification_confidence": cls.confidence,
            "provider": provider.name,
            "model": provider.model,
            "demo_mode": provider.is_demo,
            "llm_calls": usage.calls,
            "tokens": usage.tokens,
        },
        **clean_fields(raw, doc.page_count),
    }
    doc.error = None
    doc.status = DocStatus.ready
    doc.original_deleted = True
    db.commit()


def run_job(db: Session, job: Job) -> None:
    doc = db.get(Document, job.document_id)
    if doc is None:
        jobs.finish(db, job)
        return
    data = job.payload
    if data is None:
        doc.status, doc.error = DocStatus.failed, "The uploaded file is no longer available. Please upload it again."
        jobs.fail_or_retry(db, job, "payload missing", retryable=False)
        return
    try:
        process_document(db, doc, data)
        jobs.finish(db, job)
        log.info("document ready", extra={"doc": doc.id})
    except (PipelineError, AiUnavailable) as e:
        db.rollback()
        doc.status, doc.error, doc.original_deleted = DocStatus.failed, str(e), True
        jobs.fail_or_retry(db, job, str(e), retryable=False)
    except AiError as e:
        db.rollback()
        will_retry = jobs.fail_or_retry(db, job, str(e), retryable=e.retryable)
        if will_retry:
            doc.status, doc.error = DocStatus.queued, "The AI service is busy; retrying shortly."
        else:
            doc.status, doc.error, doc.original_deleted = (
                DocStatus.failed,
                "The AI service could not process this document. Please try again later.",
                True,
            )
        db.commit()
    except Exception as e:
        log.exception("pipeline crashed", extra={"doc": doc.id})
        db.rollback()
        doc.status, doc.error, doc.original_deleted = (
            DocStatus.failed,
            "Something went wrong while processing this document.",
            True,
        )
        jobs.fail_or_retry(db, job, f"{type(e).__name__}: {e}", retryable=False)
