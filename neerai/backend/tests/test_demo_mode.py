"""No-sign-in demo mode: one fixed, clearly identified principal, isolated from real users, capped, and dev-only."""
import pytest
from fastapi.testclient import TestClient

from app.core.auth import DEMO_USER
from app.core.config import ConfigError, Settings
from app.main import create_app
from app.repositories.base import FARM, Store
from app.repositories.sql import SqlRepository
from app.schemas.domain import Farm
from app.services.demo_seed import build_demo

from .conftest import make_settings


def demo_settings(**kw) -> Settings:
    return make_settings(auth_mode="demo", auto_seed=False, **kw)


@pytest.fixture()
def demo_client():
    app = create_app(demo_settings())
    with TestClient(app) as c:
        yield c, app


def test_demo_requests_work_without_a_token_and_report_demo_mode(demo_client):
    c, _ = demo_client
    assert c.get("/api/health").json()["auth_mode"] == "demo"
    farm = c.post("/api/demo/load", params={"key": "madurai"})
    assert farm.status_code == 201
    assert c.get("/api/farms").status_code == 200
    plan = c.post("/api/irrigation/plan", json={"farm_id": farm.json()["id"], "available_water": 300, "available_water_unit": "m3"})
    assert plan.status_code == 200
    job = c.post("/api/jobs", json={"farm_id": farm.json()["id"], "query": "Which field first?"})
    assert job.status_code == 202


def test_every_demo_record_belongs_to_the_fixed_demo_principal(demo_client):
    c, app = demo_client
    c.post("/api/demo/load", params={"key": "madurai"})
    repo = app.state.neerai.store.repo
    assert repo.count(FARM, owner=DEMO_USER) == 1
    assert repo.count(FARM, owner="local") == 0


def test_client_supplied_identity_is_ignored(demo_client):
    c, app = demo_client
    repo = app.state.neerai.store.repo
    # a real user's farm, written directly under a Cognito-style subject
    victim = Store(repo, "11111111-2222-3333-4444-555555555555")
    farm, _ = build_demo("madurai")
    victim.save(FARM, farm)
    spoof = {"Authorization": "Bearer anything", "X-User-Id": "11111111-2222-3333-4444-555555555555", "X-Owner": "victim"}
    assert c.get("/api/farms", headers=spoof).json() == []
    assert c.get(f"/api/farms/{farm.id}", headers=spoof).status_code == 404
    body = {"farm_name": "Spoof", "district": "Madurai", "latitude": 9.9, "longitude": 78.1, "user_id": "victim", "owner": "victim"}
    created = c.post("/api/farms", json=body, headers=spoof)
    assert created.status_code == 201
    assert repo.count(FARM, owner=DEMO_USER) == 1
    assert repo.count(FARM, owner="victim") == 0
    assert repo.count(FARM, owner="11111111-2222-3333-4444-555555555555") == 1  # untouched


def test_demo_record_caps(demo_client):
    c, _ = demo_client
    c.app.state.neerai.settings = c.app.state.neerai.settings.model_copy(update={"demo_max_farms": 2})
    body = {"farm_name": "F", "district": "Madurai", "latitude": 9.9, "longitude": 78.1}
    assert c.post("/api/farms", json=body).status_code == 201
    assert c.post("/api/farms", json=body).status_code == 201
    r = c.post("/api/farms", json=body)
    assert r.status_code == 429 and "demo limit" in r.json()["detail"]


def test_demo_job_quota_is_global_for_the_shared_principal():
    from app.schemas.jobs import JobRequest
    from app.services import jobs as jobsvc

    s = demo_settings(max_active_jobs_per_user=2, max_jobs_per_user_per_day=30)
    store = Store(SqlRepository("sqlite://"), DEMO_USER)
    farm, _ = build_demo("madurai")
    store.save(FARM, farm)

    class Silent:
        def send(self, *a):
            pass

    jobsvc.submit(s, store, Silent(), JobRequest(farm_id=farm.id, query="one"), None)
    jobsvc.submit(s, store, Silent(), JobRequest(farm_id=farm.id, query="two"), None)
    with pytest.raises(jobsvc.QuotaExceeded):
        jobsvc.submit(s, store, Silent(), JobRequest(farm_id=farm.id, query="three"), None)


def test_local_demo_has_no_request_body_bypass(demo_client):
    c, _ = demo_client
    assert c.post("/api/jobs", json={"farm_id": "x", "query": "y" * 501}).status_code == 422


# ───────────────────────── configuration: demo is dev-only ─────────────────────────

def aws(**kw):
    base = dict(env="aws", agent_mode="bedrock", repository="dynamodb", dynamodb_table="t", queue_backend="sqs",
                jobs_queue_url="https://sqs.example/q", weather_provider="openmeteo", auto_seed=False, auth_mode="demo", stage="dev",
                cors_origins="https://main.d1.amplifyapp.com", max_active_jobs_per_user=2, max_jobs_per_user_per_day=30, max_body_bytes=16384)
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_demo_mode_allowed_in_dev_aws_without_cognito_ids():
    aws().validate_runtime("api")
    aws().validate_runtime("worker")


@pytest.mark.parametrize("override,needle", [
    ({"stage": "prod"}, "STAGE=dev"), ({"stage": ""}, "STAGE=dev"),
    ({"max_jobs_per_user_per_day": 40}, "caps agent jobs"), ({"max_active_jobs_per_user": 5}, "caps agent jobs"),
    ({"max_body_bytes": 65536}, "caps request bodies"),
])
def test_demo_mode_refused_for_prod_or_loose_limits(override, needle):
    with pytest.raises(ConfigError, match=needle):
        aws(**override).validate_runtime("api")


def test_prod_with_cognito_still_requires_cognito_and_rejects_anonymous():
    with pytest.raises(ConfigError, match="AUTH_MODE"):
        aws(auth_mode="none", stage="prod").validate_runtime("api")
    with pytest.raises(ConfigError, match="COGNITO"):
        aws(auth_mode="cognito", stage="prod").validate_runtime("api")
    with pytest.raises(ConfigError):
        create_app(aws(stage="prod"))


def test_cognito_mode_unaffected_by_demo_support():
    s = make_settings(auth_mode="cognito", cognito_region="ap-south-1", cognito_user_pool_id="ap-south-1_x", cognito_client_id="c", auto_seed=False)
    with TestClient(create_app(s)) as c:
        assert c.get("/api/farms").status_code == 401
        assert c.get("/api/farms", headers={"X-User-Id": "demo-public"}).status_code == 401
