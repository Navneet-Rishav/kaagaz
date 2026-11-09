"""Question answering over one document, with page citations that are checked against what was retrieved."""

import json
import re
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.ai import get_provider
from app.ai.base import Usage, complete_json
from app.ai.prompts import REWRITE_SYSTEM, answer_system, answer_user
from app.models import Document, QaEntry, User
from app.services.retrieval import Hit, retriever

NOT_FOUND = "यह जानकारी दस्तावेज़ में नहीं मिली / Not found in this document"
_CITATION = re.compile(r"\[\s*p\.?\s*(\d+)\s*\]", re.IGNORECASE)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_WORD = re.compile(r"[\wऀ-ॣ०-ॿ]+", re.UNICODE)  # excludes the danda


class Rewrite(BaseModel):
    keywords_en: list[str] = Field(default_factory=list, max_length=10)
    keywords_hi: list[str] = Field(default_factory=list, max_length=10)


class Answer(BaseModel):
    found: bool
    answer: str = ""
    citations: list[int] = Field(default_factory=list)


@dataclass
class QaResult:
    answer: str
    language: str
    citations: list[int]
    refused: bool
    sources: list[dict] = field(default_factory=list)
    latency_ms: int = 0
    demo_mode: bool = False


def question_language(question: str) -> str:
    return "hi" if _DEVANAGARI.search(question) else "en"


def validate_citations(answer: Answer, retrieved_pages: set[int]) -> tuple[str, list[int]] | None:
    """Keeps the answer only if it cites at least one page that was actually retrieved.

    Citation markers pointing at pages that were not retrieved are removed. Returns None (refuse) when the
    model said not found, gave an empty answer, or cited nothing valid.
    """
    if not answer.found or not answer.answer.strip():
        return None
    text_pages = {int(m) for m in _CITATION.findall(answer.answer)}
    valid = sorted((text_pages | set(answer.citations)) & retrieved_pages)
    if not valid:
        return None
    cleaned = _CITATION.sub(lambda m: m.group(0) if int(m.group(1)) in retrieved_pages else "", answer.answer)
    cleaned = re.sub(r"\s+([.,;!?।])", r"\1", re.sub(r"\s{2,}", " ", cleaned)).strip()
    if not _CITATION.search(cleaned):
        cleaned = f"{cleaned} " + " ".join(f"[p.{p}]" for p in valid)
    return cleaned, valid


def ask(db: Session, user: User, doc: Document, question: str) -> QaResult:
    provider = get_provider()
    usage = Usage()
    t0 = time.perf_counter()
    language = question_language(question)

    rewrite = complete_json(
        provider, "rewrite", REWRITE_SYSTEM, json.dumps({"question": question}, ensure_ascii=False), Rewrite, usage
    )
    keywords = rewrite.keywords_en + rewrite.keywords_hi + _WORD.findall(question.lower())
    hits: list[Hit] = retriever.search(db, doc.id, keywords, k=5)

    refused = True
    answer_text, citations = NOT_FOUND, []
    if hits:
        ans = complete_json(
            provider,
            "answer",
            answer_system(language),
            answer_user(question, language, [(h.page, h.text) for h in hits]),
            Answer,
            usage,
        )
        checked = validate_citations(ans, {h.page for h in hits})
        if checked:
            answer_text, citations = checked
            refused = False

    latency = int((time.perf_counter() - t0) * 1000)
    db.add(
        QaEntry(
            document_id=doc.id,
            user_id=user.id,
            question=question,
            answer=answer_text,
            language=language,
            citations=citations,
            refused=refused,
            latency_ms=latency,
        )
    )
    db.commit()
    sources = [{"page": h.page, "text": h.text[:400]} for h in hits if h.page in citations]
    return QaResult(answer_text, language, citations, refused, sources, latency, provider.is_demo)
