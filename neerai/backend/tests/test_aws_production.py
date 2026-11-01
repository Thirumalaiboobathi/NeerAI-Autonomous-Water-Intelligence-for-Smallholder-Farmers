"""Production-path tests: Cognito auth, tenant isolation, DynamoDB repository (moto), SQS jobs, worker, config validation.

DynamoDB/SQS run against `moto` (an in-process AWS emulator) - realistic for API semantics (conditional writes, queries),
but not a substitute for the live-AWS smoke test (scripts/smoke_test.py).
"""
import json
import time
from datetime import datetime, timedelta, timezone

import boto3
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from moto import mock_aws

from app import lambda_worker
from app.core.auth import CognitoVerifier
from app.core.config import ConfigError, Settings
from app.core.logging import JsonFormatter, emit_metric, request_id_var
from app.integrations.queue import SqsQueue
from app.main import create_app
from app.repositories.base import FARM, JOB, Store
from app.repositories.dynamo import DynamoRepository
from app.repositories.sql import SqlRepository
from app.schemas.domain import Farm
from app.schemas.jobs import Job, JobRequest
from app.services import jobs as jobsvc
from app.services.jobs import JobProcessor
from app.services.weather_service import WeatherService
from tests.conftest import make_settings

REGION = "ap-south-1"
POOL, CLIENT = "ap-south-1_TestPool", "testclientid123"
ISS = f"https://cognito-idp.{REGION}.amazonaws.com/{POOL}"


# ───────────────────────── fixtures ─────────────────────────

@pytest.fixture(scope="module")
def keypair():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeKeys:
    def __init__(self, pub):
        self.pub = pub

    def get_signing_key_from_jwt(self, token):
        return self.pub


def make_token(keypair, sub="user-a", **over):
    now = datetime.now(timezone.utc)
    claims = {"sub": sub, "iss": ISS, "client_id": CLIENT, "token_use": "access", "iat": now, "exp": now + timedelta(hours=1)}
    claims.update(over)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, keypair, algorithm="RS256")


def cognito_settings(**kw):
    return make_settings(auth_mode="cognito", cognito_region=REGION, cognito_user_pool_id=POOL, cognito_client_id=CLIENT,
                         auto_seed=False, **kw)


@pytest.fixture()
def secured(keypair):
    s = cognito_settings()
    verifier = CognitoVerifier(s, FakeKeys(keypair.public_key()))
    with TestClient(create_app(s, verifier=verifier)) as c:
        yield c


def auth(keypair, sub="user-a", **over):
    return {"Authorization": f"Bearer {make_token(keypair, sub, **over)}"}


def wait_job(client, job_id, headers=None, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}", headers=headers).json()
        if j["status"] in ("succeeded", "failed"):
            return j
        time.sleep(0.2)
    raise AssertionError("job did not reach a terminal state")


# ───────────────────────── authentication ─────────────────────────

def test_unauthenticated_requests_are_rejected(secured):
    assert secured.get("/api/farms").status_code == 401
    assert secured.post("/api/jobs", json={"farm_id": "x", "query": "hi"}).status_code == 401
    assert secured.get("/api/farms", headers={"Authorization": "Bearer not.a.jwt"}).status_code == 401
    assert secured.get("/api/farms", headers={"Authorization": "Basic abc"}).status_code == 401


def test_public_endpoints_need_no_token(secured):
    assert secured.get("/health/live").json() == {"status": "alive"}
    assert secured.get("/health/ready").status_code == 200
    assert secured.get("/api/health").json()["auth_mode"] == "cognito"
    assert secured.get("/api/reference/options").status_code == 200


@pytest.mark.parametrize("over", [
    {"exp": datetime.now(timezone.utc) - timedelta(minutes=5)},      # expired
    {"iss": "https://cognito-idp.ap-south-1.amazonaws.com/other"},   # wrong issuer
    {"client_id": "someone-elses-client"},                            # token for another app client
    {"token_use": "id"},                                              # id token, not access token
    {"sub": None},                                                    # missing subject
])
def test_invalid_tokens_rejected(secured, keypair, over):
    assert secured.get("/api/farms", headers=auth(keypair, **over)).status_code == 401


def test_token_signed_with_other_key_rejected(secured):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    assert secured.get("/api/farms", headers={"Authorization": f"Bearer {make_token(other)}"}).status_code == 401


def test_alg_none_token_rejected(secured):
    forged = jwt.encode({"sub": "user-a", "iss": ISS, "client_id": CLIENT, "token_use": "access",
                         "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, key=None, algorithm="none")
    assert secured.get("/api/farms", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


# ───────────────────────── tenant isolation (IDOR) ─────────────────────────

def test_users_cannot_see_or_modify_each_others_data(secured, keypair):
    a, b = auth(keypair, "user-a"), auth(keypair, "user-b")
    assert secured.get("/api/farms", headers=a).json() == []
    fa = secured.post("/api/demo/load", params={"key": "madurai"}, headers=a).json()
    assert [f["id"] for f in secured.get("/api/farms", headers=a).json()] == [fa["id"]]
    # B sees nothing and cannot address A's farm by id through any route
    assert secured.get("/api/farms", headers=b).json() == []
    for method, url in [("get", f"/api/farms/{fa['id']}"), ("get", f"/api/farms/{fa['id']}/overview"),
                        ("patch", f"/api/farms/{fa['id']}"), ("delete", f"/api/farms/{fa['id']}")]:
        r = getattr(secured, method)(url, headers=b, **({"json": {}} if method == "patch" else {}))
        assert r.status_code == 404, (method, url)
    assert secured.post("/api/irrigation/plan", json={"farm_id": fa["id"]}, headers=b).status_code == 404
    assert secured.post("/api/jobs", json={"farm_id": fa["id"], "query": "irrigate?"}, headers=b).status_code == 404
    # A's data is intact
    assert secured.get(f"/api/farms/{fa['id']}", headers=a).status_code == 200


def test_jobs_and_executions_are_private(secured, keypair):
    a, b = auth(keypair, "user-a"), auth(keypair, "user-b")
    fa = secured.post("/api/demo/load", params={"key": "madurai"}, headers=a).json()
    job = secured.post("/api/jobs", json={"farm_id": fa["id"], "query": "Should I irrigate today?"}, headers=a).json()
    done = wait_job(secured, job["id"], a)
    assert done["status"] == "succeeded"
    assert secured.get(f"/api/jobs/{job['id']}", headers=b).status_code == 404
    assert secured.get("/api/jobs", headers=b).json() == []
    assert secured.get(f"/api/agent/executions/{done['execution_id']}", headers=a).status_code == 200
    assert secured.get(f"/api/agent/executions/{done['execution_id']}", headers=b).status_code == 404
    assert secured.get("/api/impact/summary", headers=b).json()["decisions_generated"] == 0


# ───────────────────────── async jobs (local inline queue) ─────────────────────────

def test_job_lifecycle_and_idempotency(client, farm_id):
    h = {"Idempotency-Key": "demo-key-0001"}
    r1 = client.post("/api/jobs", json={"farm_id": farm_id, "query": "I have only 400 m3. Which field first?"}, headers=h)
    assert r1.status_code == 202 and r1.json()["status"] in ("queued", "running", "succeeded")
    r2 = client.post("/api/jobs", json={"farm_id": farm_id, "query": "I have only 400 m3. Which field first?"}, headers=h)
    assert r2.status_code == 200 and r2.json()["id"] == r1.json()["id"]
    done = wait_job(client, r1.json()["id"])
    assert done["status"] == "succeeded" and done["attempts"] == 1
    ex = client.get(f"/api/agent/executions/{done['execution_id']}").json()
    assert ex["decision"] and ex["allocation"]["total_allocated_litres"] <= 400_000 + 1


def test_job_validation_and_missing_farm(client, farm_id):
    assert client.post("/api/jobs", json={"farm_id": "nope", "query": "hello"}).status_code == 404
    assert client.post("/api/jobs", json={"farm_id": farm_id, "query": ""}).status_code == 422
    assert client.post("/api/jobs", json={"farm_id": farm_id, "query": "x" * 501}).status_code == 422
    assert client.post("/api/jobs", json={"farm_id": farm_id, "query": "hi", "weather_scenario": "bogus"}).status_code == 422
    assert client.post("/api/jobs", json={"farm_id": farm_id, "query": "hi"}, headers={"Idempotency-Key": "bad key!"}).status_code == 422
    assert client.get("/api/jobs/job_missing").status_code == 404


def test_per_user_active_job_quota(farm_id):
    s = make_settings(max_active_jobs_per_user=1)
    store = Store(SqlRepository("sqlite://"))
    from app.services.demo_seed import build_demo
    farm, fields = build_demo("madurai")
    store.save(FARM, farm)

    class Silent:
        def send(self, *a):
            pass

    q = Silent()
    jobsvc.submit(s, store, q, JobRequest(farm_id=farm.id, query="one"), None)
    with pytest.raises(jobsvc.QuotaExceeded):
        jobsvc.submit(s, store, q, JobRequest(farm_id=farm.id, query="two"), None)


def test_request_size_limit_and_request_id(client):
    r = client.post("/api/jobs", content=b"x" * 70000, headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    r = client.get("/api/health", headers={"X-Request-ID": "trace-12345678"})
    assert r.headers["x-request-id"] == "trace-12345678"
    assert client.get("/api/health", headers={"X-Request-ID": "bad id\n"}).headers["x-request-id"] != "bad id"


# ───────────────────────── processor semantics ─────────────────────────

def _processor_env(**kw):
    s = make_settings(**kw)
    store = Store(SqlRepository("sqlite://"))
    from app.services.demo_seed import build_demo
    farm, fields = build_demo("madurai")
    own = store.scoped("user-a")
    own.save(FARM, farm)
    from app.repositories.base import FIELD
    for f in fields:
        own.save(FIELD, f, parent=farm.id)
    return s, store, own, farm, JobProcessor(s, store, WeatherService(s))


def _queued_job(own, farm):
    job = Job(request=JobRequest(farm_id=farm.id, query="Should I irrigate today?"))
    own.save_conditional(JOB, job, if_absent=True)
    return job


def test_replayed_message_is_a_noop_after_success():
    s, store, own, farm, p = _processor_env()
    job = _queued_job(own, farm)
    msg = {"owner": "user-a", "job_id": job.id, "correlation_id": "c-1"}
    assert p.process(msg) == "done"
    first = own.get(JOB, job.id, Job)
    assert first.status == "succeeded" and first.attempts == 1
    assert p.process(msg) == "done"                      # duplicate delivery
    again = own.get(JOB, job.id, Job)
    assert again.attempts == 1 and again.version == first.version
    from app.repositories.base import EXECUTION
    assert own.count(EXECUTION) == 1                      # no duplicate side effect


def test_forged_or_unknown_messages_are_dropped():
    s, store, own, farm, p = _processor_env()
    job = _queued_job(own, farm)
    assert p.process({"owner": "user-b", "job_id": job.id}) == "done"       # other tenant's id: not found, dropped
    assert own.get(JOB, job.id, Job).status == "queued"                      # untouched
    assert p.process({"owner": "", "job_id": job.id}) == "done"
    assert p.process({"job_id": "job_unknown"}) == "done"
    assert p.process({}) == "done"


def test_transient_failure_retries_then_fails_terminally(monkeypatch):
    s, store, own, farm, p = _processor_env(job_max_attempts=2)
    job = _queued_job(own, farm)
    msg = {"owner": "user-a", "job_id": job.id}

    def boom(*a, **k):
        raise RuntimeError("bedrock exploded")

    monkeypatch.setattr("app.services.jobs.run_assessment", boom)
    assert p.process(msg, 1) == "retry"
    j = own.get(JOB, job.id, Job)
    assert j.status == "queued" and j.attempts == 1 and j.error.retryable
    assert p.process(msg, 2) == "done"
    j = own.get(JOB, job.id, Job)
    assert j.status == "failed" and j.attempts == 2 and j.error.code == "agent_error"
    assert "bedrock exploded" not in j.model_dump_json()                      # internal detail never exposed
    assert p.process(msg, 3) == "done"                                         # terminal: ignored


def test_job_timeout_is_a_transient_failure(monkeypatch):
    s, store, own, farm, p = _processor_env(job_max_attempts=1, job_timeout_s=10)
    object.__setattr__(p.settings, "job_timeout_s", 0.2)
    job = _queued_job(own, farm)
    monkeypatch.setattr("app.services.jobs.run_assessment", lambda *a, **k: time.sleep(1.5))
    assert p.process({"owner": "user-a", "job_id": job.id}, 1) == "done"
    assert own.get(JOB, job.id, Job).status == "failed"


def test_running_job_with_live_lease_is_not_stolen():
    s, store, own, farm, p = _processor_env()
    job = _queued_job(own, farm)
    running = job.model_copy(update={"status": "running", "version": 1, "attempts": 1})
    assert own.save_conditional(JOB, running, expect_version=0)
    assert p.process({"owner": "user-a", "job_id": job.id}) == "retry"
    stale = running.model_copy(update={"updated_at": datetime.now(timezone.utc) - timedelta(hours=1), "version": 2})
    assert own.save_conditional(JOB, stale, expect_version=1)
    assert p.process({"owner": "user-a", "job_id": job.id}) == "done"        # expired lease: reclaimed and finished
    assert own.get(JOB, job.id, Job).status == "succeeded"


# ───────────────────────── DynamoDB (moto) ─────────────────────────

@pytest.fixture()
def dynamo():
    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        yield DynamoRepository("t", region=REGION)


def test_dynamo_crud_listing_and_count(dynamo):
    s = Store(dynamo, "user-a")
    a, b = Farm(farm_name="A"), Farm(farm_name="B")
    s.save(FARM, a)
    s.save(FARM, b, parent="grp")
    assert s.count(FARM) == 2
    assert {f.farm_name for f in s.list(FARM, Farm)} == {"A", "B"}
    assert [f.farm_name for f in s.list(FARM, Farm, parent="grp")] == ["B"]
    a.farm_name = "A2"
    s.save(FARM, a)
    assert s.get(FARM, a.id, Farm).farm_name == "A2" and s.count(FARM) == 2
    s.delete(FARM, b.id)
    assert s.get(FARM, b.id, Farm) is None and s.count(FARM) == 1


def test_dynamo_tenant_isolation(dynamo):
    a, b = Store(dynamo, "user-a"), Store(dynamo, "user-b")
    f = Farm(farm_name="mine")
    a.save(FARM, f)
    assert b.get(FARM, f.id, Farm) is None and b.list(FARM, Farm) == [] and b.count(FARM) == 0
    b.delete(FARM, f.id)                                     # deleting someone else's id is a no-op
    assert a.get(FARM, f.id, Farm) is not None


def test_dynamo_conditional_writes_and_ttl(dynamo):
    s = Store(dynamo, "user-a")
    j = Job(request=JobRequest(farm_id="f", query="q"))
    assert s.save_conditional(JOB, j, if_absent=True)
    assert not s.save_conditional(JOB, j, if_absent=True)                       # idempotent create
    upd = j.model_copy(update={"status": "running", "version": 1})
    assert s.save_conditional(JOB, upd, expect_version=0)
    assert not s.save_conditional(JOB, j.model_copy(update={"version": 1}), expect_version=0)   # stale writer loses
    assert s.get(JOB, j.id, Job).status == "running"
    s.save(JOB, Job(id="job_expired", request=JobRequest(farm_id="f", query="q")), ttl_seconds=1)
    item = dynamo.table.get_item(Key={"pk": "USER#user-a", "sk": "job#job_expired"})["Item"]
    assert int(item["ttl"]) > time.time() - 5
    dynamo.table.update_item(Key={"pk": "USER#user-a", "sk": "job#job_expired"}, UpdateExpression="SET #t = :p",
                             ExpressionAttributeNames={"#t": "ttl"}, ExpressionAttributeValues={":p": int(time.time()) - 10})
    assert s.get(JOB, "job_expired", Job) is None and all(x.id != "job_expired" for x in s.list(JOB, Job))


def test_sql_tenant_isolation_and_conditional():
    repo = SqlRepository("sqlite://")
    a, b = Store(repo, "a"), Store(repo, "b")
    f = Farm(farm_name="x")
    a.save(FARM, f)
    assert b.get(FARM, f.id, Farm) is None and b.count(FARM) == 0
    j = Job(request=JobRequest(farm_id="f", query="q"))
    assert a.save_conditional(JOB, j, if_absent=True) and not a.save_conditional(JOB, j, if_absent=True)
    assert not a.save_conditional(JOB, j.model_copy(update={"version": 5}), expect_version=3)


# ───────────────────────── SQS + worker (moto) ─────────────────────────

def test_sqs_worker_end_to_end_with_dynamo():
    with mock_aws():
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}])
        sqs = boto3.client("sqs", region_name=REGION)
        url = sqs.create_queue(QueueName="jobs")["QueueUrl"]
        s = make_settings(repository="dynamodb", dynamodb_table="t", aws_region=REGION, queue_backend="sqs", jobs_queue_url=url,
                          auto_seed=False)
        repo = DynamoRepository("t", region=REGION)
        own = Store(repo, "user-a")
        from app.services.demo_seed import build_demo
        from app.repositories.base import FIELD
        farm, fields = build_demo("madurai")
        own.save(FARM, farm)
        for f in fields:
            own.save(FIELD, f, parent=farm.id)

        job, created = jobsvc.submit(s, own, SqsQueue(url, REGION), JobRequest(farm_id=farm.id, query="Should I irrigate today?"), "idem-key-0001")
        assert created and job.status == "queued"
        _, created2 = jobsvc.submit(s, own, SqsQueue(url, REGION), JobRequest(farm_id=farm.id, query="Should I irrigate today?"), "idem-key-0001")
        assert not created2
        assert int(sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])["Attributes"]["ApproximateNumberOfMessages"]) == 1

        # a forged message for an unknown job is consumed and dropped without side effects
        sqs.send_message(QueueUrl=url, MessageBody=json.dumps({"owner": "user-z", "job_id": "job_forged"}))
        sqs.send_message(QueueUrl=url, MessageBody="not json")           # poison message: left for redelivery/DLQ

        monkeypatch_env(s, repo)
        for _ in range(3):   # drain like the Lambda event source mapping would (batch size 1)
            r = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1, AttributeNames=["ApproximateReceiveCount"], VisibilityTimeout=1)
            for m in r.get("Messages", []):
                ev = {"Records": [{"messageId": m["MessageId"], "receiptHandle": m["ReceiptHandle"], "body": m["Body"],
                                   "attributes": {"ApproximateReceiveCount": m["Attributes"]["ApproximateReceiveCount"]}}]}
                out = lambda_worker.handler(ev)
                if not out["batchItemFailures"]:
                    sqs.delete_message(QueueUrl=url, ReceiptHandle=m["ReceiptHandle"])   # what Lambda's ESM does on success
        done = own.get(JOB, job.id, Job)
        assert done.status == "succeeded" and done.execution_id
        assert lambda_worker.handler({"Records": [{"messageId": "m", "receiptHandle": "r", "body": "not json", "attributes": {}}]}) == {
            "batchItemFailures": [{"itemIdentifier": "m"}]}                    # poison message -> reported failure -> DLQ after retries


def monkeypatch_env(s, repo):
    """Point the Lambda worker module at the moto-backed processor (it normally builds it from environment variables)."""
    lambda_worker._processor = JobProcessor(s, Store(repo), WeatherService(s))
    lambda_worker._sqs = None


def test_worker_backoff_grows_with_jitter_and_is_capped():
    assert all(10 <= lambda_worker.backoff_seconds(1) <= 20 for _ in range(20))
    assert lambda_worker.backoff_seconds(10) <= 390


def test_worker_reports_transient_failures_for_redelivery(monkeypatch):
    s, store, own, farm, p = _processor_env(job_max_attempts=3, jobs_queue_url="")
    job = _queued_job(own, farm)
    lambda_worker._processor = p
    monkeypatch.setattr("app.services.jobs.run_assessment", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(lambda_worker, "_client", lambda: type("C", (), {"change_message_visibility": staticmethod(lambda **kw: None)})())
    ev = {"Records": [{"messageId": "m1", "receiptHandle": "r", "body": json.dumps({"owner": "user-a", "job_id": job.id}),
                       "attributes": {"ApproximateReceiveCount": "1"}}]}
    assert lambda_worker.handler(ev) == {"batchItemFailures": [{"itemIdentifier": "m1"}]}
    assert own.get(JOB, job.id, Job).status == "queued"
    monkeypatch.undo()
    assert lambda_worker.handler(ev) == {"batchItemFailures": []}              # next delivery succeeds
    assert own.get(JOB, job.id, Job).status == "succeeded"


# ───────────────────────── production configuration ─────────────────────────

def prod(**kw):
    base = dict(env="aws", agent_mode="bedrock", repository="dynamodb", dynamodb_table="t", queue_backend="sqs",
                jobs_queue_url="https://sqs.example/q", weather_provider="openmeteo", auto_seed=False, auth_mode="cognito",
                cognito_region=REGION, cognito_user_pool_id=POOL, cognito_client_id=CLIENT, cors_origins="https://d123.cloudfront.net")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_valid_production_config_passes():
    prod().validate_runtime("api")
    prod(auth_mode="none", cognito_user_pool_id="", cors_origins="").validate_runtime("worker")


@pytest.mark.parametrize("override,needle", [
    ({"agent_mode": "demo"}, "AGENT_MODE"), ({"repository": "sql"}, "REPOSITORY"), ({"queue_backend": "inline"}, "QUEUE_BACKEND"),
    ({"auth_mode": "none"}, "AUTH_MODE"), ({"cognito_client_id": ""}, "COGNITO"), ({"auto_seed": True}, "AUTO_SEED"),
    ({"cors_origins": "http://localhost:5173"}, "CORS_ORIGINS"), ({"cors_origins": "*"}, "CORS_ORIGINS"),
])
def test_unsafe_production_config_fails_fast(override, needle):
    with pytest.raises(ConfigError, match=needle):
        prod(**override).validate_runtime("api")


def test_weather_provider_must_be_explicit_in_production():
    s = Settings(_env_file=None, env="aws", agent_mode="bedrock", repository="dynamodb", queue_backend="sqs", jobs_queue_url="u",
                 auto_seed=False, auth_mode="cognito", cognito_region=REGION, cognito_user_pool_id=POOL, cognito_client_id=CLIENT,
                 cors_origins="https://x.cloudfront.net")
    with pytest.raises(ConfigError, match="WEATHER_PROVIDER"):
        s.validate_runtime("api")


def test_create_app_refuses_unsafe_production_config():
    with pytest.raises(ConfigError):
        create_app(Settings(_env_file=None, env="aws"))


def test_sync_agent_routes_disabled_in_production(keypair):
    s = cognito_settings()
    app = create_app(s, verifier=CognitoVerifier(s, FakeKeys(keypair.public_key())))
    with TestClient(app) as c:
        h = auth(keypair)
        fa = c.post("/api/demo/load", params={"key": "madurai"}, headers=h).json()
        app.state.neerai.settings = s.model_copy(update={"env": "aws"})   # flip after startup validation (test harness only)
        assert c.post("/api/agent/chat", json={"farm_id": fa["id"], "message": "hi"}, headers=h).status_code == 410
        assert c.post("/api/irrigation/assess", json={"farm_id": fa["id"]}, headers=h).status_code == 410


def test_readiness_fails_when_repository_is_down_but_liveness_stays_up(client):
    def broken(*a, **k):
        raise RuntimeError("db down")

    client.app.state.neerai.store.repo.get_raw = broken
    assert client.get("/health/ready").status_code == 503
    assert client.get("/health/live").status_code == 200


def test_readiness_ignores_weather_provider_state():
    s = make_settings(weather_provider="openmeteo", weather_timeout_s=0.001)
    with TestClient(create_app(s)) as c:
        assert c.get("/health/ready").status_code == 200


# ───────────────────────── logging ─────────────────────────

def test_json_logs_and_metrics(capsys):
    import logging

    rec = logging.LogRecord("neerai", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    token = request_id_var.set("req-123456")
    try:
        out = json.loads(JsonFormatter().format(rec))
    finally:
        request_id_var.reset(token)
    assert out["msg"] == "hello world" and out["request_id"] == "req-123456" and out["level"] == "INFO"
    emit_metric("JobFailed", 1, Stage="test")
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["JobFailed"] == 1 and line["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "NeerAI"
