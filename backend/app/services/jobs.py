"""A small job queue in Postgres, worked by a background thread inside the API process.

Claiming uses SELECT ... FOR UPDATE SKIP LOCKED: concurrent workers skip rows another worker has locked, so
a job is never processed twice, and the queue survives restarts because it lives in the database (Render's
free tier stops idle services). Retryable failures back off; jobs stuck in "running" after a crash are re-queued.
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import session_factory
from app.models import Job, JobStatus

log = logging.getLogger("kaagaz.jobs")

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=10)


def enqueue(db: Session, document_id: str, payload: bytes) -> Job:
    job = Job(document_id=document_id, payload=payload)
    db.add(job)
    return job


def claim_next(db: Session, now: datetime | None = None) -> Job | None:
    now = now or datetime.now(UTC)
    job = db.scalars(
        select(Job)
        .where(Job.status == JobStatus.queued, Job.run_after <= now)
        .order_by(Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if job is None:
        db.rollback()
        return None
    job.status = JobStatus.running
    job.locked_at = now
    job.attempts += 1
    db.commit()
    return job


def requeue_stale(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    res = db.execute(
        update(Job).where(Job.status == JobStatus.running, Job.locked_at < now - STALE_AFTER).values(status=JobStatus.queued)
    )
    db.commit()
    return res.rowcount or 0


def finish(db: Session, job: Job) -> None:
    job.status = JobStatus.done
    job.payload = None
    job.last_error = None
    db.commit()


def fail_or_retry(db: Session, job: Job, error: str, retryable: bool, now: datetime | None = None) -> bool:
    """Returns True if the job will be retried."""
    now = now or datetime.now(UTC)
    job.last_error = error[:1000]
    if retryable and job.attempts < MAX_ATTEMPTS:
        job.status = JobStatus.queued
        job.run_after = now + timedelta(seconds=30 * 2 ** (job.attempts - 1))
        db.commit()
        return True
    job.status = JobStatus.failed
    job.payload = None  # never keep the original file around after giving up
    db.commit()
    return False


def process_next(db: Session) -> bool:
    """Claims one job and runs the pipeline on it. Returns False when there was nothing to do."""
    from app.services.pipeline import run_job

    job = claim_next(db)
    if job is None:
        return False
    run_job(db, job)
    return True


class Worker:
    def __init__(self, poll_seconds: float) -> None:
        self._poll = poll_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="kaagaz-worker", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _run(self) -> None:
        from app.services.demo_data import purge_expired_demo_users

        log.info("worker started")
        last_purge = 0.0
        while not self._stop.is_set():
            try:
                with session_factory()() as db:
                    if time.monotonic() - last_purge > 600:
                        purge_expired_demo_users(db)
                        last_purge = time.monotonic()
                    requeue_stale(db)
                    while not self._stop.is_set() and process_next(db):
                        pass
            except Exception:
                log.exception("worker loop error")
            self._stop.wait(self._poll)
