"""FastAPI application factory."""
from __future__ import annotations

import hmac
import logging
import re
import threading
import time
import uuid
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import AppState, health_router, router, seed_demo
from .core.auth import CognitoVerifier
from .core.config import Settings, get_settings
from .core.logging import configure_logging, request_id_var
from .integrations.queue import InlineQueue, SqsQueue
from .repositories.base import Store
from .services import demo_seed
from .services.jobs import JobProcessor
from .services.weather_service import WeatherService

log = logging.getLogger("neerai")


def build_repository(s: Settings):
    if s.repository == "dynamodb":
        from .repositories.dynamo import DynamoRepository

        return DynamoRepository(s.dynamodb_table, region=s.aws_region)
    from .repositories.sql import SqlRepository

    return SqlRepository(s.database_url)


class RateLimiter:
    """Fixed-window per-client limiter (in-memory; use API Gateway throttling in AWS for a shared limit)."""

    def __init__(self, per_minute: int):
        self.per_minute, self.hits, self.lock = per_minute, defaultdict(list), threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.time()
        with self.lock:
            q = [t for t in self.hits[key] if now - t < 60]
            ok = len(q) < self.per_minute
            if ok:
                q.append(now)
            self.hits[key] = q
            return ok


_REQ_ID = re.compile(r"^[A-Za-z0-9\-_]{8,64}$")
_PUBLIC_PATHS = ("/health/", "/api/health")


def create_app(settings: Settings | None = None, repository=None, verifier=None, queue=None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    settings.validate_runtime("api")
    app = FastAPI(title="NeerAI API", version="1.1.0", docs_url=None if settings.env == "aws" else "/docs",
                  redoc_url=None, openapi_url=None if settings.env == "aws" else "/openapi.json",
                  description="Autonomous water intelligence for smallholder farmers. Decision support only - never controls pumps.")
    store = Store(repository or build_repository(settings))
    weather = WeatherService(settings)
    st = AppState(settings=settings, store=store, weather=weather)
    if settings.auth_mode == "cognito":
        st.verifier = verifier or CognitoVerifier(settings)
    elif settings.auth_mode == "demo":
        log.warning("DEMO MODE: no authentication; every request is the shared principal 'demo-public' (stage=%s)", settings.stage or "-")
    if queue is None:
        queue = SqsQueue(settings.jobs_queue_url, settings.aws_region) if settings.queue_backend == "sqs" else None
    if queue is None:  # inline: same processor the worker uses, run in a background thread
        processor = JobProcessor(settings, store, weather)

        def _inline(msg: dict) -> None:
            for attempt in range(1, settings.job_max_attempts + 1):
                if processor.process(msg, attempt) == "done":
                    return
                time.sleep(min(2 * attempt, 5))

        queue = InlineQueue(_inline)
    st.queue = queue
    app.state.neerai = st
    limiter = RateLimiter(settings.rate_limit_per_minute) if settings.env != "aws" and settings.rate_limit_per_minute > 0 else None

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "Authorization", "Idempotency-Key", "X-Request-ID"], allow_credentials=False)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        rid = rid if _REQ_ID.match(rid) else uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            path = request.url.path
            public = path.startswith(_PUBLIC_PATHS)
            if settings.origin_verify_secret and request.method != "OPTIONS" and not public:
                sent = request.headers.get("x-origin-verify", "")
                if not hmac.compare_digest(sent.encode(), settings.origin_verify_secret.encode()):
                    return JSONResponse({"detail": "forbidden"}, status_code=403)
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > settings.max_body_bytes:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
            if limiter and not public and request.method != "OPTIONS":
                client = request.client.host if request.client else "unknown"
                if not limiter.allow(client):
                    return JSONResponse({"detail": "rate limit exceeded; retry shortly"}, status_code=429)
            resp = await call_next(request)
            resp.headers["X-Content-Type-Options"] = "nosniff"
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["X-Request-ID"] = rid
            return resp
        finally:
            request_id_var.reset(token)

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    app.include_router(router)
    app.include_router(health_router)

    if settings.auto_seed and settings.auth_mode == "none" and not store.count("farm"):
        try:
            for key in demo_seed.demo_keys():
                seed_demo(st, key)
        except Exception as e:  # noqa: BLE001 - app should still start without seed data
            log.warning("demo seed skipped: %s", e)
    return app
