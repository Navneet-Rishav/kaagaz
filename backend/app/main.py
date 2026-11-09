"""FastAPI app: request IDs, JSON logs, CORS limited to the frontend origin, typed errors, /healthz."""

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import get_settings
from app.db import get_engine
from app.errors import install_error_handlers
from app.routes import auth


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
    app = FastAPI(title="Kaagaz API", version="0.1.0")
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
        return {"status": "ok" if db == "up" else "degraded", "db": db}

    app.include_router(auth.router)
    return app
