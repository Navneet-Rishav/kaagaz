"""FastAPI app: request IDs, JSON logs, CORS limited to the frontend origin, typed errors, /healthz."""

import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.ai import get_provider
from app.config import get_settings
from app.db import get_engine
from app.errors import install_error_handlers
from app.routes import auth, documents, voice
from app.services.jobs import Worker


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"level": record.levelname.lower(), "msg": record.getMessage(), "logger": record.name}
        for key in ("request_id", "method", "path", "status", "ms"):
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, ensure_ascii=False)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("kaagaz")
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False


log = logging.getLogger("kaagaz.http")


def create_app() -> FastAPI:
    settings = get_settings()
    _configure_logging()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        worker = Worker(settings.worker_poll_seconds) if settings.run_worker else None
        if worker:
            worker.start()
        yield
        if worker:
            worker.stop()

    app = FastAPI(title="Kaagaz API", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_id(request: Request, call_next):
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = rid
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        extra = {"request_id": rid, "method": request.method, "path": request.url.path, "status": response.status_code}
        log.info("request", extra={**extra, "ms": round((time.perf_counter() - start) * 1000)})
        return response

    @app.get("/healthz")
    def healthz() -> dict:
        try:
            with get_engine().connect() as c:
                c.execute(text("select 1"))
            db = "up"
        except Exception:
            db = "down"
        out = {"status": "ok" if db == "up" else "degraded", "db": db}
        if commit := os.environ.get("RENDER_GIT_COMMIT"):
            out["commit"] = commit[:7]
        return out

    @app.get("/api/meta")
    def meta() -> dict:
        """What the UI needs to label results honestly: is real AI on, and which features work."""
        p = get_provider()
        return {
            "provider": p.name,
            "model": p.model,
            "demo_mode": p.is_demo,
            "ocr_enabled": not p.is_demo,
            "voice_enabled": not p.is_demo,
            "limits": {"max_upload_mb": settings.max_upload_mb, "max_pages": settings.max_pages},
        }

    app.include_router(auth.router)
    app.include_router(documents.router)
    app.include_router(voice.router)
    return app
