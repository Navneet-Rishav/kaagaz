"""Kaagaz eval: runs the labelled set through the real pipeline and Q&A code and reports
field-extraction accuracy, citation validity, refusal correctness and p50/p95 latency.

    cd backend
    python -m evals.run                      # AI_PROVIDER from .env (demo by default)
    AI_PROVIDER=sarvam python -m evals.run   # real model: paid API calls (~2 per document + 2 per question)

It needs a Postgres in DATABASE_URL (it creates a temporary user and deletes it at the end). The demo documents
use their prepared page text (the stand-in for an OCR result), so the eval measures extraction and Q&A, not OCR.

With the demo provider this only proves the script works: the rule-based provider was written next to these
documents, so its scores are NOT a model evaluation and must not be published.
"""

import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai import get_provider
from app.models import Document, User
from app.security import hash_password
from app.services.demo_data import DEMO_DIR
from app.services.pipeline import process_document
from app.services.qa import ask
from evals.dataset import DOCS, QUESTIONS


@dataclass
class Report:
    provider: str
    is_demo: bool
    fields_total: int = 0
    fields_value_ok: int = 0
    fields_page_ok: int = 0
    doc_type_ok: int = 0
    answerable: int = 0
    answered_with_valid_citation: int = 0
    answer_text_ok: int = 0
    should_refuse: int = 0
    refused_correctly: int = 0
    wrongly_refused: int = 0
    latencies_ms: list[int] = field(default_factory=list)
    rows: list[str] = field(default_factory=list)


def _norm(s: object) -> str:
    return re.sub(r"[\s,₹.()]+", "", str(s)).lower()


def value_matches(expected: str, got: object) -> bool:
    """Lenient match: numbers compare as numbers; text matches if one contains the other (ignoring spaces,
    commas and the "(DEMO)" suffix the documents carry)."""
    if got in (None, ""):
        return False
    e, g = _norm(expected), _norm(str(got).replace("(DEMO)", "").replace("(डेमो)", ""))
    try:
        return float(e) == float(g)
    except ValueError:
        return bool(e) and (e in g or g in e)


def run(db: Session) -> Report:
    provider = get_provider()
    rep = Report(provider=f"{provider.name}/{provider.model}", is_demo=provider.is_demo)
    user = User(email=f"eval-{int(time.time())}@kaagaz.eval", name="Eval", password_hash=hash_password("x" * 16), is_demo=True)
    db.add(user)
    db.commit()
    docs: dict[str, Document] = {}
    try:
        for filename, spec in DOCS.items():
            data = (Path(DEMO_DIR) / filename).read_bytes()
            doc = Document(
                user_id=user.id,
                filename=filename,
                content_type="application/pdf",
                size_bytes=len(data),
                sha256=f"eval-{filename}",
                language=spec["language"],
                is_demo=True,  # use the prepared page text
            )
            db.add(doc)
            db.commit()
            process_document(db, doc, data)
            docs[filename] = doc
            rep.doc_type_ok += int(doc.doc_type is not None and doc.doc_type.value == spec["doc_type"])
            for label in spec["fields"]:
                got = (doc.fields or {}).get(label.name, {})
                ok_v = value_matches(label.value, got.get("value"))
                ok_p = ok_v and got.get("page") == label.page
                rep.fields_total += 1
                rep.fields_value_ok += ok_v
                rep.fields_page_ok += ok_p
                rep.rows.append(
                    f"field  {'OK ' if ok_p else 'val' if ok_v else 'XX '} {filename[:22]:<22} {label.name:<22} expected={label.value!r} got={got.get('value')!r} p{got.get('page')}"
                )

        for q in QUESTIONS:
            t0 = time.perf_counter()
            r = ask(db, user, docs[q.doc], q.question)
            rep.latencies_ms.append(int((time.perf_counter() - t0) * 1000))
            if q.page is None:
                rep.should_refuse += 1
                rep.refused_correctly += r.refused
                status = "OK " if r.refused else "XX "
            else:
                rep.answerable += 1
                if r.refused:
                    rep.wrongly_refused += 1
                    status = "XX "
                else:
                    cite_ok = q.page in r.citations
                    text_ok = q.contains.lower() in r.answer.lower()
                    rep.answered_with_valid_citation += cite_ok
                    rep.answer_text_ok += cite_ok and text_ok
                    status = "OK " if cite_ok and text_ok else "XX "
            rep.rows.append(
                f"answer {status} {q.question[:40]:<40} expected_page={q.page} cited={r.citations} refused={r.refused}"
            )
    finally:
        db.delete(user)  # cascades to the documents, pages, chunks and Q&A history
        db.commit()
    return rep


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "n/a"


def print_report(rep: Report) -> None:
    print(f"provider: {rep.provider}")
    if rep.is_demo:
        print("NOTE: demo provider (rule-based, written next to these documents). This run only shows the script works;")
        print("      the numbers below are NOT a model evaluation and must not be published.\n")
    for row in rep.rows:
        print(row)
    lat = sorted(rep.latencies_ms)
    p95 = statistics.quantiles(lat, n=20)[18] if len(lat) > 1 else (lat[0] if lat else 0)
    print()
    print(f"document type correct:        {pct(rep.doc_type_ok, len(DOCS))}")
    print(f"field values correct:         {pct(rep.fields_value_ok, rep.fields_total)}")
    print(f"field value + page correct:   {pct(rep.fields_page_ok, rep.fields_total)}")
    print(f"answers citing the right page:{pct(rep.answered_with_valid_citation, rep.answerable):>14}")
    print(f"answers right page + text:    {pct(rep.answer_text_ok, rep.answerable)}")
    print(f"answerable but refused:       {pct(rep.wrongly_refused, rep.answerable)}")
    print(f"refusal correctness:          {pct(rep.refused_correctly, rep.should_refuse)}")
    print(f"Q&A latency: p50 {statistics.median(lat) if lat else 0:.0f} ms, p95 {p95:.0f} ms ({len(lat)} questions)")


def main() -> int:
    from app.db import session_factory

    with session_factory()() as db:
        print_report(run(db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
