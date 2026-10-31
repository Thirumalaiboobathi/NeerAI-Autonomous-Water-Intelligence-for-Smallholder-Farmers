import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.calculations.pipeline import build_context
from app.services.demo_seed import build_demo


def make_settings(**kw) -> Settings:
    base = dict(database_url="sqlite://", agent_mode="demo", weather_provider="mock", weather_scenario="uncertain_rain",
                auto_seed=True, rate_limit_per_minute=100000)
    base.update(kw)
    return Settings(**base)


@pytest.fixture()
def settings():
    return make_settings()


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture()
def madurai():
    farm, fields = build_demo("madurai")
    return farm, fields, build_context(farm, fields)


@pytest.fixture()
def farm_id(client):
    return next(f["id"] for f in client.get("/api/farms").json() if "Melur" in f["farm_name"])
