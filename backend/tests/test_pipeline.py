from datetime import UTC, datetime, timedelta

from app.ai import set_provider
from app.ai.base import AiError, AiUnavailable
from app.ai.demo import DemoProvider
from app.models import Chunk, DocStatus, Document, Job, JobStatus, Page, User
from app.services import jobs
from app.services.demo_data import create_demo_user, purge_expired_demo_users
from tests.pdfgen import RENT_EN, make_pdf


def _user(db) -> User:
    u = User(email="t@example.com", name="T", password_hash="x")
    db.add(u)
    db.commit()
    return u


def _doc(db, user, data: bytes, **kw) -> Document:
    d = Document(
        user_id=user.id,
        filename=kw.pop("filename", "rent.pdf"),
        content_type="application/pdf",
        size_bytes=len(data),
        sha256=kw.pop("sha", "h1"),
        **kw,
    )
    db.add(d)
    db.flush()
    jobs.enqueue(db, d.id, data)
    db.commit()
    return d


def _drain(db) -> None:
    while jobs.process_next(db):
        pass


def test_text_layer_pdf_goes_through_all_steps(db) -> None:
    u = _user(db)
    d = _doc(db, u, make_pdf(RENT_EN))
    _drain(db)
    db.refresh(d)
    assert d.status == DocStatus.ready and d.error is None
    assert d.text_source == "pdf_text" and d.page_count == 2
    assert d.doc_type.value == "rent_agreement"
    assert d.fields["monthly_rent_inr"] == {"value": "18500", "page": 1, "confidence": "medium"}
    assert d.fields["security_deposit_inr"]["page"] == 2
    assert d.fields["_meta"]["demo_mode"] is True
    # Only masked text is stored, plus counts of what was masked
    pages = db.query(Page).filter_by(document_id=d.id).order_by(Page.page_number).all()
    assert "9876543210" not in pages[0].masked_text and "<PHONE>" in pages[0].masked_text
    assert "501004567890" not in pages[0].masked_text and "<BANK_ACCOUNT>" in pages[0].masked_text
    assert d.pii_counts == {"PHONE": 1, "BANK_ACCOUNT": 1, "IFSC": 1}
    assert db.query(Chunk).filter_by(document_id=d.id).count() >= 2
    # The original file is gone
    job = db.query(Job).filter_by(document_id=d.id).one()
    assert job.status == JobStatus.done and job.payload is None and d.original_deleted


def test_scanned_file_without_ocr_fails_with_a_clear_message(db) -> None:
    u = _user(db)
    d = _doc(db, u, make_pdf(["", ""]))
    _drain(db)
    db.refresh(d)
    assert d.status == DocStatus.failed
    assert "OCR" in d.error
    assert db.query(Job).filter_by(document_id=d.id).one().payload is None


class FlakyProvider(DemoProvider):
    def __init__(self, failures: int) -> None:
        self.failures = failures

    def chat(self, task, system, user, schema=None):
        if self.failures > 0:
            self.failures -= 1
            raise AiError("Sarvam returned HTTP 503", retryable=True, status=503)
        return super().chat(task, system, user, schema)


def test_retryable_ai_errors_back_off_then_succeed(db) -> None:
    u = _user(db)
    d = _doc(db, u, make_pdf(RENT_EN))
    set_provider(FlakyProvider(failures=1))
    try:
        assert jobs.process_next(db)
        job = db.query(Job).filter_by(document_id=d.id).one()
        db.refresh(d)
        assert job.status == JobStatus.queued and job.attempts == 1 and job.payload is not None
        assert d.status == DocStatus.queued and "retrying" in d.error
        assert job.run_after > datetime.now(UTC)
        assert jobs.process_next(db) is False  # not due yet
        job.run_after = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        _drain(db)
        db.refresh(d)
        assert d.status == DocStatus.ready
    finally:
        set_provider(None)


def test_gives_up_after_max_attempts(db) -> None:
    u = _user(db)
    d = _doc(db, u, make_pdf(RENT_EN))
    set_provider(FlakyProvider(failures=99))
    try:
        for _ in range(jobs.MAX_ATTEMPTS):
            jobs.process_next(db)
            db.query(Job).update({Job.run_after: datetime.now(UTC) - timedelta(seconds=1)})
            db.commit()
        job = db.query(Job).filter_by(document_id=d.id).one()
        db.refresh(d)
        assert job.status == JobStatus.failed and job.attempts == jobs.MAX_ATTEMPTS and job.payload is None
        assert d.status == DocStatus.failed and "try again later" in d.error
    finally:
        set_provider(None)


def test_claim_skips_locked_rows(db) -> None:
    """Two sessions claiming at once never get the same job (FOR UPDATE SKIP LOCKED)."""
    from app.db import session_factory

    u = _user(db)
    _doc(db, u, make_pdf(RENT_EN), sha="a")
    _doc(db, u, make_pdf(RENT_EN), sha="b", filename="b.pdf")
    s1, s2 = session_factory()(), session_factory()()
    try:
        from sqlalchemy import select

        locked = s1.scalars(
            select(Job).where(Job.status == JobStatus.queued).order_by(Job.id).limit(1).with_for_update(skip_locked=True)
        ).first()
        other = jobs.claim_next(s2)
        assert locked is not None and other is not None and other.id != locked.id
        s1.rollback()
    finally:
        s1.close()
        s2.close()


def test_stale_running_jobs_are_requeued(db) -> None:
    u = _user(db)
    d = _doc(db, u, make_pdf(RENT_EN))
    job = jobs.claim_next(db)
    assert job and job.document_id == d.id
    assert jobs.requeue_stale(db, now=datetime.now(UTC) + timedelta(minutes=11)) == 1
    db.refresh(job)
    assert job.status == JobStatus.queued


def test_unavailable_capability_is_not_retried(db) -> None:
    class NoOcr(DemoProvider):
        def chat(self, *a, **k):
            raise AiUnavailable("nope")

    u = _user(db)
    d = _doc(db, u, make_pdf(RENT_EN))
    set_provider(NoOcr())
    try:
        _drain(db)
        db.refresh(d)
        assert d.status == DocStatus.failed and d.error == "nope"
        assert db.query(Job).filter_by(document_id=d.id).one().attempts == 1
    finally:
        set_provider(None)


def test_demo_user_gets_three_prepared_documents(db) -> None:
    u = create_demo_user(db)
    _drain(db)
    docs = {d.filename: d for d in db.query(Document).filter_by(user_id=u.id)}
    assert set(docs) == {"rent-agreement-bilingual.pdf", "electricity-bill.pdf", "khasra-khatauni-hindi.pdf"}
    for d in docs.values():
        assert d.status == DocStatus.ready, d.error
        assert d.text_source == "demo_prepared"
    rent, bill, khasra = docs["rent-agreement-bilingual.pdf"], docs["electricity-bill.pdf"], docs["khasra-khatauni-hindi.pdf"]
    assert rent.doc_type.value == "rent_agreement" and rent.fields["monthly_rent_inr"]["value"] == "18500"
    assert rent.fields["start_date"]["value"] == "01/04/2026" and rent.fields["end_date"]["value"] == "28/02/2027"
    assert rent.pii_counts == {"AADHAAR": 1, "PAN": 1, "PHONE": 2, "EMAIL": 1, "BANK_ACCOUNT": 1, "IFSC": 1}
    assert bill.doc_type.value == "electricity_bill" and bill.fields["amount_due_inr"]["value"] == "2846"
    assert khasra.doc_type.value == "property_record" and khasra.fields["khasra_number"]["value"] == "512/3"
    # Devanagari-digit Aadhaar and mobile on the Hindi record were masked
    assert khasra.pii_counts == {"AADHAAR": 1, "PHONE": 1}


def test_expired_demo_users_are_purged_with_their_documents(db) -> None:
    u = create_demo_user(db)
    real = _user(db)
    assert purge_expired_demo_users(db, now=datetime.now(UTC) + timedelta(hours=25)) == 1
    assert db.get(User, u.id) is None and db.query(Document).filter_by(user_id=u.id).count() == 0
    assert db.get(User, real.id) is not None
