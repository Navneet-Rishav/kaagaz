from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def _normalize(url: str) -> str:
    # Neon/Render hand out postgres:// or postgresql:// URLs; we use the psycopg 3 driver.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        # Small pool: Render free tier + Neon free tier have tight connection limits.
        _engine = create_engine(_normalize(get_settings().database_url), pool_size=5, max_overflow=2, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()


def reset_engine() -> None:
    """Tests use this after changing DATABASE_URL."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None
