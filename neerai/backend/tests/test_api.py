import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.conftest import make_settings


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["agent_mode"] == "demo"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_openapi_documented(client):
    assert "/api/irrigation/assess" in client.get("/openapi.json").json()["paths"]


def test_demo_farms_seeded(client):
    farms = client.get("/api/farms").json()
    assert len(farms) == 2 and all(f["is_demo"] for f in farms)
    assert client.get("/api/demo/scenarios").json()["weather_scenarios"]


def test_farm_and_field_crud(client):
    f = client.post("/api/farms", json={"farmer_name": "Test", "farm_name": "T", "water_available_litres": 50000}).json()
    fld = client.post("/api/fields", json={"farm_id": f["id"], "name": "A", "area": 1, "area_unit": "acre", "crop": "Maize",
                                           "stage": "mid"})
    assert fld.status_code == 201
    body = fld.json()
    assert body["area_ha"] == pytest.approx(0.4047, abs=1e-3) and body["crop"] == "maize"
    patched = client.patch(f"/api/fields/{body['id']}", json={"soil_moisture_pct": 15, "stage": "late"}).json()
    assert patched["soil_moisture_pct"] == 15 and patched["stage"] == "late"
    assert len(client.get("/api/fields", params={"farm_id": f["id"]}).json()) == 1
    assert client.delete(f"/api/fields/{body['id']}").status_code == 204
    assert client.delete(f"/api/farms/{f['id']}").status_code == 204
    assert client.get(f"/api/farms/{f['id']}").status_code == 404


@pytest.mark.parametrize("payload", [
    {"name": "X", "area": -1, "crop": "paddy"}, {"name": "X", "area": 1, "crop": "dragonfruit"},
    {"name": "X", "area": 1, "crop": "paddy", "soil_type": "moonrock"}, {"name": "X", "area": 1, "crop": "paddy", "stage": "flowering"},
    {"name": "X", "area": 1, "crop": "paddy", "soil_moisture_pct": 400},
])
def test_field_validation(client, farm_id, payload):
    assert client.post("/api/fields", json={"farm_id": farm_id, **payload}).status_code == 422


def test_unknown_farm_404(client):
    assert client.get("/api/farms/nope").status_code == 404
    assert client.post("/api/irrigation/assess", json={"farm_id": "nope"}).status_code == 404


def test_overview_uses_real_backend_numbers(client, farm_id):
    r = client.get(f"/api/farms/{farm_id}/overview").json()
    assert r["result"]["weather"]["simulated"] is True
    assert r["result"]["allocation"]["total_allocated_litres"] <= r["result"]["allocation"]["available_litres"]


def test_field_weather_endpoint_and_scenarios(client, farm_id):
    fid = client.get("/api/fields", params={"farm_id": farm_id}).json()[0]["id"]
    assert client.get(f"/api/weather/{fid}").json()["simulated"] is True
    hot = client.get(f"/api/weather/{fid}", params={"weather_scenario": "heatwave"}).json()
    assert hot["heat_risk"] == "high"
    assert client.get(f"/api/weather/{fid}", params={"weather_scenario": "nope"}).status_code == 422


def test_plan_recalculates_with_water_and_priorities(client, farm_id):
    base = client.post("/api/irrigation/plan", json={"farm_id": farm_id}).json()
    low = client.post("/api/irrigation/plan", json={"farm_id": farm_id, "available_water": 300, "available_water_unit": "m3"}).json()
    assert low["allocation"]["available_litres"] == 300_000
    assert low["allocation"]["total_allocated_litres"] <= 300_000 < base["allocation"]["total_allocated_litres"] + 1
    assert low["allocation"]["scarcity_mode"] and low["water_input_source"] == "farmer-adjusted value"
    paddy = next(f for f in base["context"]["fields"] if f["crop"] == "paddy")["field_id"]
    pinned = client.post("/api/water/allocate", json={"farm_id": farm_id, "available_water": 300, "available_water_unit": "m3",
                                                       "priority_overrides": {paddy: 3.0}}).json()
    g = lambda r: next(a["allocated_litres"] for a in r["allocation"]["allocations"] if a["crop"] == "paddy")  # noqa: E731
    assert g(pinned) > g(low)


def test_plan_save_and_report_export(client, farm_id):
    saved = client.post("/api/irrigation/plan", json={"farm_id": farm_id, "save": True, "label": "Morning plan"}).json()
    assert saved["plan_id"]
    assert len(client.get("/api/irrigation/plans", params={"farm_id": farm_id}).json()) == 1
    md = client.get(f"/api/irrigation/plans/{saved['plan_id']}/report")
    assert md.status_code == 200 and "Why this decision?" in md.text and "never controls pumps" in md.text
    assert "SIMULATED" in md.text
    assert "Water budget" in client.post("/api/irrigation/report", json={"farm_id": farm_id}).text


def test_negative_water_rejected(client, farm_id):
    assert client.post("/api/irrigation/plan", json={"farm_id": farm_id, "available_water": -5}).status_code == 422


def test_assess_runs_agents_and_stores_trace(client, farm_id):
    ex = client.post("/api/irrigation/assess", json={"farm_id": farm_id, "query": "Should I irrigate my paddy today?"}).json()
    assert ex["status"] == "completed" and len(ex["steps"]) >= 10
    got = client.get(f"/api/agent/executions/{ex['id']}").json()
    assert got["id"] == ex["id"] and got["decision"]["requires_farmer_approval"] is True
    assert client.get("/api/agent/executions/nope").status_code == 404


def test_chat_endpoint_and_tamil(client, farm_id):
    ex = client.post("/api/agent/chat", json={"farm_id": farm_id, "message": "Explain my water plan in Tamil."}).json()
    assert ex["language"] == "ta" and "லிட்டர்" in ex["answer"]
    assert client.post("/api/agent/chat", json={"farm_id": farm_id, "message": ""}).status_code == 422
    assert client.post("/api/agent/chat", json={"farm_id": farm_id, "message": "x" * 600}).status_code == 422


def test_simulate_endpoint(client, farm_id):
    r = client.post("/api/scenarios/simulate", json={"farm_id": farm_id, "scenarios": ["severe_shortage", "heatwave"],
                                                      "custom": [{"name": "mine", "title": "Mine", "rainfall_mm": 20,
                                                                  "rain_probability_pct": 80, "water_factor": 0.7}]})
    assert r.status_code == 200
    body = r.json()
    assert len(body["scenarios"]) == 3 and "hypothetical" in body["disclaimer"].lower()
    assert client.post("/api/scenarios/simulate", json={"farm_id": farm_id, "scenarios": ["bogus"]}).status_code == 422
    assert client.post("/api/scenarios/simulate", json={"farm_id": farm_id}).status_code == 422
    assert client.post("/api/scenarios/simulate", json={"farm_id": farm_id, "custom": [{"rainfall_mm": -1}]}).status_code == 422


def test_impact_summary_counts_real_activity_and_separates_savings(client, farm_id):
    empty = client.get("/api/impact/summary").json()
    assert empty["decisions_generated"] == 0 and empty["fields_supported"] == 5
    client.post("/api/irrigation/assess", json={"farm_id": farm_id})
    client.post("/api/scenarios/simulate", json={"farm_id": farm_id, "scenarios": ["drip_irrigation", "unexpected_rain"]})
    s = client.get("/api/impact/summary").json()
    assert s["decisions_generated"] == 1 and s["scenarios_evaluated"] == 2
    kinds = {x["kind"]: x for x in s["savings"]}
    assert set(kinds) == {"estimated_potential", "simulated", "measured"}
    assert kinds["measured"]["litres"] == 0 and "no" in kinds["measured"]["note"].lower()
    assert kinds["simulated"]["litres"] > 0
    assert "Baseline" in s["baseline_definition"]


def test_demo_load_is_idempotent_and_reset_works(client):
    n = len(client.get("/api/farms").json())
    client.post("/api/demo/load", params={"key": "madurai"})
    assert len(client.get("/api/farms").json()) == n
    client.post("/api/demo/load", params={"key": "madurai", "reset": True})
    assert len(client.get("/api/farms").json()) == n
    assert client.post("/api/demo/load", params={"key": "zzz"}).status_code == 404


def test_rate_limit_returns_429():
    app = create_app(make_settings(rate_limit_per_minute=3))
    with TestClient(app) as c:
        codes = [c.get("/api/farms").status_code for _ in range(6)]
        assert 429 in codes
        assert c.get("/api/health").status_code == 200  # health is exempt


def test_cors_only_allows_configured_origins(client):
    ok = client.options("/api/farms", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    bad = client.options("/api/farms", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-origin" not in bad.headers


def test_agent_timeout_returns_504(monkeypatch, farm_id):
    import time
    from app.api import routes

    app = create_app(make_settings(agent_timeout_s=0.2))
    monkeypatch.setattr(routes, "run_assessment", lambda *a, **k: time.sleep(1.5))
    with TestClient(app) as c:
        fid = next(f["id"] for f in c.get("/api/farms").json())
        assert c.post("/api/irrigation/assess", json={"farm_id": fid}).status_code == 504
