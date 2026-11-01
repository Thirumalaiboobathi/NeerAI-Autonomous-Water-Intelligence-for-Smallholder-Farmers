"""Async agent jobs: submission (API side) and processing (worker side).

Reliability properties:
* Idempotent submit: a client-supplied Idempotency-Key maps to a deterministic job id; creation is a conditional write.
* At-least-once delivery is safe: processing claims the job with an optimistic-lock transition, terminal jobs are ignored,
  and the only side effect (the execution record) has a deterministic id derived from the job id, so a replay overwrites it.
* Messages for unknown jobs are dropped (forged/poisoned messages cannot create work or touch another user's data).
* Bounded retries: transient failures return the job to `queued` and leave the SQS message for redelivery; after
  `job_max_attempts` the job is marked `failed`. SQS' own redrive policy moves exhausted messages to the DLQ.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import timedelta
from typing import Literal, Optional

from ..core.config import Settings
from ..core.logging import emit_metric, request_id_var
from ..integrations.queue import JobQueue
from ..repositories.base import EXECUTION, FARM, FIELD, JOB, Store
from ..schemas.domain import AgentExecution, Farm, Field_, new_id, now_utc
from ..schemas.jobs import Job, JobError, JobRequest
from .audit import record as audit
from .weather_service import WeatherService

log = logging.getLogger("neerai.jobs")

def run_assessment(*args, **kwargs):
    """Lazy wrapper: Strands is imported only in the worker, keeping the API Lambda's cold start short."""
    from ..agents.orchestrator import run_assessment as _run

    return _run(*args, **kwargs)


Outcome = Literal["done", "retry"]
_IDEM = re.compile(r"^[A-Za-z0-9_\-]{8,100}$")


class QuotaExceeded(Exception):
    pass


class EnqueueFailed(Exception):
    pass


def job_id_for(owner: str, key: Optional[str]) -> str:
    if not key:
        return new_id("job")
    if not _IDEM.match(key):
        raise ValueError("Idempotency-Key must be 8-100 characters of letters, digits, '-' or '_'")
    return "job_" + hashlib.sha256(f"{owner}:{key}".encode()).hexdigest()[:24]


def _ttl(settings: Settings) -> int:
    return settings.job_ttl_days * 86400


def submit(settings: Settings, store: Store, queue: JobQueue, req: JobRequest, idempotency_key: Optional[str]) -> tuple[Job, bool]:
    """Create and enqueue a job. Returns (job, created); `created` is False when the idempotency key was already used."""
    jid = job_id_for(store.owner, idempotency_key)
    existing = store.get(JOB, jid, Job)
    if existing:
        return existing, False
    if not store.get(FARM, req.farm_id, Farm):
        raise KeyError("farm not found")
    recent = store.list(JOB, Job, limit=200)
    cutoff = now_utc() - timedelta(days=1)
    if sum(1 for j in recent if not j.terminal) >= settings.max_active_jobs_per_user:
        raise QuotaExceeded("too many agent runs in progress; wait for one to finish")
    if sum(1 for j in recent if j.created_at >= cutoff) >= settings.max_jobs_per_user_per_day:
        raise QuotaExceeded("daily agent-run limit reached")
    job = Job(id=jid, request=req, correlation_id=request_id_var.get())
    if not store.save_conditional(JOB, job, ttl_seconds=_ttl(settings), if_absent=True):
        return store.get(JOB, jid, Job) or job, False  # lost a creation race: someone else's identical request won
    try:
        queue.send(store.owner, job.id, job.correlation_id)
    except Exception as e:  # noqa: BLE001
        log.error("enqueue failed: %s", type(e).__name__)
        failed = job.model_copy(update={"status": "failed", "progress": "could not be queued", "version": job.version + 1,
                                        "error": JobError(code="enqueue_failed", message="The job could not be queued; please retry.", retryable=True)})
        store.save(JOB, failed, ttl_seconds=_ttl(settings))
        raise EnqueueFailed from e
    audit(store, "job_submitted", job.id)
    return job, True


class JobProcessor:
    def __init__(self, settings: Settings, store: Store, weather: WeatherService):
        self.settings, self.store, self.weather = settings, store, weather

    def _save(self, store: Store, job: Job, **upd) -> Job:
        return job.model_copy(update={**upd, "updated_at": now_utc(), "version": job.version + 1})

    def process(self, msg: dict, receive_count: int = 1) -> Outcome:
        owner, jid = str(msg.get("owner", "")), str(msg.get("job_id", ""))
        token = request_id_var.set(str(msg.get("correlation_id", "-"))[:64])
        try:
            return self._process(owner, jid)
        finally:
            request_id_var.reset(token)

    def _process(self, owner: str, jid: str) -> Outcome:
        s = self.settings
        store = self.store.scoped(owner) if owner else None
        job = store.get(JOB, jid, Job) if store else None
        if store is None or job is None:
            log.warning("dropping message for unknown job")
            emit_metric("JobMessageDropped", 1)
            return "done"
        if job.terminal:
            return "done"  # replayed/duplicate delivery of a finished job
        lease = timedelta(seconds=s.job_timeout_s + 30)
        if job.status == "running" and now_utc() - job.updated_at < lease:
            return "retry"  # another worker holds the lease; the message will reappear
        attempts = job.attempts + 1
        if attempts > s.job_max_attempts:
            self._fail(store, job, JobError(code="max_attempts", message="The assessment could not be completed. Please try again.", retryable=True))
            return "done"
        claimed = self._save(store, job, status="running", attempts=attempts, progress="running agents", error=None)
        if not store.save_conditional(JOB, claimed, ttl_seconds=_ttl(s), expect_version=job.version):
            return "retry"  # lost the claim race
        t0 = time.perf_counter()
        req = claimed.request
        try:
            farm = store.get(FARM, req.farm_id, Farm)
            if farm is None:
                self._fail(store, claimed, JobError(code="farm_not_found", message="The farm no longer exists."))
                return "done"
            fields = sorted(store.list(FIELD, Field_, parent=farm.id), key=lambda f: f.created_at)
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent") as pool:
                fut = pool.submit(
                    run_assessment, farm, fields, req.query, req.language, settings=s, available_litres=req.available_litres,
                    priority_overrides=req.priority_overrides, weather_scenario=req.weather_scenario,
                    weather_fetcher=lambda lat, lon, d, _sc=req.weather_scenario: self.weather.get(lat, lon, _sc, d))
                try:
                    ex: AgentExecution = fut.result(timeout=s.job_timeout_s)
                except FutureTimeout:
                    pool.shutdown(wait=False, cancel_futures=True)
                    raise TimeoutError("job timeout") from None
            ex.id = "exec_" + claimed.id.removeprefix("job_")  # deterministic -> a replay overwrites instead of duplicating
            store.save(EXECUTION, ex, parent=farm.id)
            ms = int((time.perf_counter() - t0) * 1000)
            fallbacks = sum(1 for st in ex.steps if st.kind == "fallback" or st.status == "fallback")
            done = self._save(store, claimed, status="succeeded", progress="complete", execution_id=ex.id, error=None,
                              metrics={"duration_ms": ms, "mode": ex.mode, "steps": len(ex.steps), "fallbacks": fallbacks,
                                       "model_id": s.bedrock_model_id if ex.mode == "bedrock" else "demo"})
            store.save(JOB, done, ttl_seconds=_ttl(s))
            audit(store, "decision_generated", ex.id)
            emit_metric("JobSucceeded", 1)
            emit_metric("JobDurationMs", ms, "Milliseconds")
            emit_metric("AgentFallbacks", fallbacks)
            log.info("job succeeded in %d ms (%d steps, %d fallbacks)", ms, len(ex.steps), fallbacks)
            return "done"
        except ValueError as e:  # bad input: retrying cannot help
            self._fail(store, claimed, JobError(code="invalid_request", message=str(e)[:200]))
            return "done"
        except Exception as e:  # noqa: BLE001 - transient: bounded retry, then terminal failure
            log.warning("job attempt %d/%d failed: %s", attempts, s.job_max_attempts, type(e).__name__)
            emit_metric("JobAttemptFailed", 1)
            if attempts >= s.job_max_attempts:
                self._fail(store, claimed, JobError(code="agent_error", message="The assessment could not be completed. Please try again.", retryable=True))
                return "done"
            store.save(JOB, self._save(store, claimed, status="queued", progress="retrying", error=JobError(
                code=type(e).__name__, message="Temporary problem; retrying.", retryable=True)), ttl_seconds=_ttl(s))
            return "retry"

    def _fail(self, store: Store, job: Job, err: JobError) -> None:
        store.save(JOB, self._save(store, job, status="failed", progress="failed", error=err), ttl_seconds=_ttl(self.settings))
        emit_metric("JobFailed", 1)
        log.error("job failed: %s", err.code)
