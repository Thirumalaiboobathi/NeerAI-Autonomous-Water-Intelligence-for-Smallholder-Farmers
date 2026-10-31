"""FastAPI application factory."""
from __future__ import annotations

import hmac
import logging
import threading
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.routes import AppState, router, seed_demo
from .core.config import Settings, get_settings
from .core.logging import configure_logging
from .repositories.base import Store
from .services import demo_seed
from .services.weather_service import WeatherService

log = logging.getLogger("neerai")


def build_repository(s: Settings):
    if s.repository == "dynamodb":
        from .repositories.dynamo import DynamoRepository

        return DynamoRepository(s.dynamodb_table, region=s.bedrock_region)
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


def create_app(settings: Settings | None = None, repository=None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()
    app = FastAPI(title="NeerAI API", version="1.0.0",
                  description="Autonomous water intelligence for smallholder farmers. Decision support only - never controls pumps.")
    store = Store(repository or build_repository(settings))
    app.state.neerai = AppState(settings=settings, store=store, weather=WeatherService(settings))
    limiter = RateLimiter(settings.rate_limit_per_minute)

    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["GET", "POST", "PATCH", "DELETE"],
                       allow_headers=["Content-Type", "Authorization"], allow_credentials=False)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if settings.origin_verify_secret and request.method != "OPTIONS":
            sent = request.headers.get("x-origin-verify", "")
            if not hmac.compare_digest(sent.encode(), settings.origin_verify_secret.encode()):
                return JSONResponse({"detail": "forbidden"}, status_code=403)
        if request.url.path != "/api/health" and request.method != "OPTIONS":
            client = request.client.host if request.client else "unknown"
            if not limiter.allow(client):
                return JSONResponse({"detail": "rate limit exceeded; retry shortly"}, status_code=429)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error: %s", type(exc).__name__)
        return JSONResponse({"detail": "internal error"}, status_code=500)

    app.include_router(router)

    if settings.auto_seed and not store.count("farm"):
        try:
            st = app.state.neerai
            for key in demo_seed.demo_keys():
                seed_demo(st, key)
        except Exception as e:  # noqa: BLE001 - app should still start without seed data
            log.warning("demo seed skipped: %s", e)
    return app

