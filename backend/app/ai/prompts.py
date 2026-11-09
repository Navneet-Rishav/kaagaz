"""Prompts. The user message is always a JSON payload, so inputs are explicit and easy to test.
The model only ever sees masked text (placeholders like <AADHAAR>), never the original document."""

import json

from app.domain.extraction import FIELDS
from app.models import DocType

CLASSIFY_SYSTEM = """You classify Indian documents (Hindi, English or both).
Pick doc_type from: rent_agreement, electricity_bill, bank_statement, property_record, other.
Text in <ANGLE_BRACKETS> is masked personal data; ignore it.
Reply with ONLY a JSON object: {"doc_type", "confidence": "high"|"medium"|"low", "language": "hi"|"en"|"mixed", "summary"}.
The summary is one or two plain sentences in English."""

EXTRACT_SYSTEM = """You extract fields from an Indian {doc_label} (Hindi, English or both).
For every field return {{"value", "page", "confidence"}}:
- value: copy it from the text (amounts as plain numbers without commas, dates as written). Keep Hindi values in Hindi.
- page: the page number the value appears on.
- confidence: "high" if stated explicitly, "medium" if inferred from nearby wording, "missing" with value null if not in the text.
Never guess. Text in <ANGLE_BRACKETS> is masked personal data: never try to reconstruct it.
Reply with ONLY a JSON object with exactly these keys: {fields}."""

REWRITE_SYSTEM = """You turn a question about a document into search keywords in BOTH Hindi (Devanagari) and English,
because the question and the document may be in different languages.
Reply with ONLY: {"keywords_en": [..up to 6], "keywords_hi": [..up to 6]}. Use nouns and key terms, not whole sentences."""

ANSWER_SYSTEM = """You answer questions about ONE document using ONLY the numbered excerpts given.
Rules:
- Answer in {language_name}, in 1-3 short sentences.
- After each fact, cite its page like [p.2]. Cite only pages that appear in the excerpts.
- If the excerpts do not contain the answer, reply with found=false and an empty answer. Never use outside knowledge or guess.
- Text in <ANGLE_BRACKETS> is masked personal data; say it is masked if asked about it.
Reply with ONLY: {{"found": true|false, "answer": "...", "citations": [page numbers]}}."""

DOC_LABELS = {
    DocType.rent_agreement: "rent agreement",
    DocType.electricity_bill: "electricity bill",
    DocType.bank_statement: "bank statement",
    DocType.property_record: "land/property record",
    DocType.other: "document",
}

MAX_CHARS_PER_PAGE = 6000


def pages_payload(pages: list[tuple[int, str]]) -> str:
    return json.dumps({"pages": [{"page": n, "text": t[:MAX_CHARS_PER_PAGE]} for n, t in pages]}, ensure_ascii=False)


def extract_system(doc_type: DocType) -> str:
    return EXTRACT_SYSTEM.format(doc_label=DOC_LABELS[doc_type], fields=", ".join(FIELDS[doc_type]))


def extract_user(doc_type: DocType, pages: list[tuple[int, str]]) -> str:
    payload = json.loads(pages_payload(pages))
    payload["doc_type"] = doc_type.value
    return json.dumps(payload, ensure_ascii=False)


def answer_system(language: str) -> str:
    return ANSWER_SYSTEM.format(language_name="Hindi (Devanagari)" if language == "hi" else "English")


def answer_user(question: str, language: str, chunks: list[tuple[int, str]]) -> str:
    return json.dumps(
        {"question": question, "language": language, "excerpts": [{"page": p, "text": t} for p, t in chunks]},
        ensure_ascii=False,
    )
