from sqlalchemy import text

from app.models import Chunk, Document, User
from app.services.retrieval import clean_keywords, has_trgm, retriever


def _doc_with_chunks(db, chunks: list[tuple[int, str]]) -> str:
    u = User(email="r@example.com", name="R", password_hash="x")
    db.add(u)
    db.flush()
    d = Document(user_id=u.id, filename="d.pdf", content_type="application/pdf", size_bytes=1, sha256="r1")
    db.add(d)
    db.flush()
    db.add_all(Chunk(document_id=d.id, page=p, idx=i, text=t) for i, (p, t) in enumerate(chunks))
    db.commit()
    return d.id


def test_clean_keywords_dedupes_and_strips_punctuation() -> None:
    assert clean_keywords(["Rent?", "rent", "  ", "security deposit!", "किराया।"]) == ["rent", "security deposit", "किराया"]


def test_full_text_search_or_across_languages(db) -> None:
    doc = _doc_with_chunks(db, [(1, "Monthly rent is ₹18,500."), (2, "मासिक किराया ₹18,500 है।"), (3, "Pets need consent.")])
    pages = {h.page for h in retriever.search(db, doc, ["rent", "किराया"])}
    assert pages == {1, 2}


def test_search_is_scoped_to_one_document(db) -> None:
    doc = _doc_with_chunks(db, [(1, "Monthly rent is ₹18,500.")])
    assert retriever.search(db, "some-other-doc", ["rent"]) == []
    assert retriever.search(db, doc, []) == []


def test_fuzzy_fallback_finds_typos(db) -> None:
    """FTS misses 'deposite'; the fallback (pg_trgm, or ILIKE without it) still has to behave."""
    doc = _doc_with_chunks(db, [(1, "The security deposit is ₹37,000."), (2, "Notice period is two months.")])
    hits = retriever.search(db, doc, ["deposite"])
    if has_trgm(db):
        assert [h.page for h in hits] == [1]
    else:
        assert hits == []  # ILIKE needs the exact substring; documented limitation without pg_trgm


def test_pg_trgm_present_in_ci(db) -> None:
    """CI uses the postgres:16 image, which ships pg_trgm; the local pgserver build does not."""
    import os

    if os.environ.get("CI"):
        assert db.execute(text("SELECT 1 FROM pg_extension WHERE extname='pg_trgm'")).first() is not None
