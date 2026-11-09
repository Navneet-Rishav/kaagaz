"""Demo accounts and sample documents.

Every click on "Try the demo" creates a fresh, isolated demo account, so visitors never see each other's
uploads. It is seeded with three synthetic documents (obviously fake data) that run through the normal
pipeline. Demo accounts are deleted after 24 hours.
"""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Document, User
from app.security import hash_password
from app.services import jobs

DEMO_DIR = Path(__file__).resolve().parent.parent.parent / "demo_docs"
DEMO_TTL = timedelta(hours=24)
# (file, language picked at upload)
DEMO_FILES = [
    ("rent-agreement-bilingual.pdf", "hi-IN"),
    ("electricity-bill.pdf", "en-IN"),
    ("khasra-khatauni-hindi.pdf", "hi-IN"),
]


def create_demo_user(db: Session) -> User:
    user = User(
        email=f"demo-{secrets.token_hex(6)}@kaagaz.demo",
        name="Demo User",
        is_demo=True,
        password_hash=hash_password(secrets.token_urlsafe(24)),
    )
    db.add(user)
    db.flush()
    for filename, language in DEMO_FILES:
        path = DEMO_DIR / filename
        if not path.exists():
            continue
        data = path.read_bytes()
        doc = Document(
            user_id=user.id,
            filename=filename,
            content_type="application/pdf",
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            language=language,
            is_demo=True,
        )
        db.add(doc)
        db.flush()
        jobs.enqueue(db, doc.id, data)
    db.commit()
    return user


def purge_expired_demo_users(db: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    res = db.execute(delete(User).where(User.is_demo.is_(True), User.created_at < now - DEMO_TTL))
    db.commit()
    return res.rowcount or 0
