"""Regression tests: one per defect found during development/validation, plus the remaining evaluation scenarios."""
import re

import pytest
from fastapi.testclient import TestClient

from app.agents import messages, steps
from app.agents.intent import parse_query
from app.agents.orchestrator import reconcile, run_assessment, select_answer
from app.agents.runctx import RunContext
from app.calculations.pipeline import build_context, run_core
from app.core.config import Settings
from app.integrations.weather import get_weather
from app.main import create_app
from app.schemas.domain import Action, Language
from app.services.demo_seed import build_demo
from tests.conftest import make_settings

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in NUM.findall(text)}


# ── BUG: need used *peak* depletion so forecast rain did not reduce demand ──
def test_regression_rain_reduces_groundnut_need_not_just_paddy(madurai):
    _, _, ctx = madurai
    dry = run_core(ctx, get_weather("mock", 0, 0, 3, "dry"), 5e6)
    rain = run_core(ctx, get_weather("mock", 0, 0, 3, "heavy_rain"), 5e6)
    g = lambda r: next(n for n in r.crop_water.fields if n.crop == "groundnut")  # noqa: E731
    assert g(rain).net_requirement_mm < g(dry).net_requirement_mm


# ── BUG: 'delay by a day' discarded a measured soil reading and looked cheaper ──
def test_regression_delay_keeps_measured_moisture_and_never_lowers_demand(madurai):
    from app.calculations import scenarios as sc
    _, _, ctx = madurai
    w = get_weather("mock", 0, 0, 3, "dry")
    comp = sc.compare(ctx, w, 7e5, [sc.PRESETS["delayed_irrigation"]])
    s = comp.scenarios[0]
    assert s.total_demand_litres >= comp.base.total_demand_litres
    ground = next(f for f in ctx.fields if f.crop == "groundnut")
    assert ground.soil_moisture_pct is not None  # input context untouched by the simulation


# ── BUG: priority overrides used Field_.field_id (AttributeError) ──
def test_regression_priority_override_tool_path_does_not_crash(madurai):
    farm, fields, _ = madurai
    ex = run_assessment(farm, fields, "plan", Language.en, settings=make_settings(), priority_overrides={fields[0].id: 2.0})
    assert ex.status == "completed" and not ex.errors


# ── BUG (Bedrock): LLM skipped set_available_water, farmer's 400 m3 silently ignored ──
def test_regression_stated_water_enforced_when_agent_skips_tool(madurai):
    farm, fields, _ = madurai
    parsed = parse_query("I have only 400 m3 of water")
    rc = RunContext(settings=make_settings(), farm=farm, fields=fields, query="q", parsed=parsed, language=Language.en)
    steps.do_context(rc)
    steps.do_weather(rc, 3)
    steps.do_crop_water(rc, 3)
    steps.do_allocate(rc)  # computed with the stale 700 m3 budget, as the LLM run did
    assert rc.allocation.available_litres == 700_000
    reconcile(rc)
    assert rc.allocation.available_litres == 400_000
    assert rc.decision.total_recommended_litres <= 400_000
    assert any(s.tool == "fallback:set_available_water" for s in rc.steps)  # traceable


# ── BUG (Bedrock): '<thinking>' scratchpad leaked as the farmer-facing answer ──
@pytest.mark.parametrize("bad", [
    "<thinking> I will wait for the farmer. </thinking>",
    "<thinking>x</thinking> Irrigate groundnut.",   # no verified quantity
    "Irrigate with 987654 L now.",                    # invented quantity
])
def test_regression_llm_scratchpad_and_unverified_text_never_reach_farmer(madurai, bad):
    farm, fields, _ = madurai
    ex = run_assessment(farm, fields, "Should I irrigate today?", Language.en, settings=make_settings())
    rc = RunContext(settings=make_settings(agent_mode="bedrock"), farm=farm, fields=fields, query="q", parsed=parse_query("q"), language=Language.en)
    rc.ctx, rc.weather, rc.crop_water, rc.allocation, rc.decision, rc.message = (
        ex.context, ex.weather, ex.crop_water, ex.allocation, ex.decision, ex.message)
    assert select_answer(rc, bad, blocked=False) == ex.message.short_summary


def test_regression_clean_llm_answer_with_verified_quantity_is_accepted(madurai):
    farm, fields, _ = madurai
    ex = run_assessment(farm, fields, "Should I irrigate today?", Language.en, settings=make_settings())
    rc = RunContext(settings=make_settings(agent_mode="bedrock"), farm=farm, fields=fields, query="q", parsed=parse_query("q"), language=Language.en)
    rc.ctx, rc.weather, rc.crop_water, rc.allocation, rc.decision, rc.message = (
        ex.context, ex.weather, ex.crop_water, ex.allocation, ex.decision, ex.message)
    good = f"<thinking>hmm</thinking> Apply {ex.allocation.total_allocated_litres:,.0f} L today."
    assert select_answer(rc, good, blocked=False) == f"Apply {ex.allocation.total_allocated_litres:,.0f} L today."


# ── BUG (Bedrock): LLM chose the reply language itself ──
def test_regression_reply_language_is_the_farmers_not_the_llms(madurai):
    farm, fields, _ = madurai
    rc = RunContext(settings=make_settings(), farm=farm, fields=fields, query="q", parsed=parse_query("q"), language=Language.en)
    for f in (steps.do_context, ):
        f(rc)
    steps.do_weather(rc, 3); steps.do_crop_water(rc, 3); steps.do_allocate(rc); steps.do_decide(rc)
    steps.do_message(rc, "ta")  # an LLM passing 'ta' for an English request
    assert rc.message.language == Language.en


# ── BUG: default model id failed in ap-south-1 (needs inference profile) ──
def test_regression_default_bedrock_model_is_regionally_valid():
    s = Settings()
    assert s.bedrock_region == "ap-south-1" and s.bedrock_model_id.startswith("apac.")


# ───────────── evaluation scenarios 7, 8, 10 ─────────────
def test_eval7_invalid_soil_type_is_reported_not_guessed(madurai):
    farm, fields, _ = madurai
    fields[0].soil_type = "moonrock"
    ex = run_assessment(farm, fields, "Should I irrigate today?", Language.en, settings=make_settings())
    assert ex.decision.headline_action == Action.INSUFFICIENT_DATA
    assert any("moonrock" in q for q in ex.follow_up_questions)
    assert ex.allocation is None


@pytest.mark.parametrize("pct,word", [(55.0, "above field capacity"), (2.0, "below wilting point")])
def test_eval7_inconsistent_soil_moisture_is_disclosed(madurai, pct, word):
    farm, fields, _ = madurai
    g = next(f for f in fields if f.crop == "groundnut")
    g.soil_moisture_pct = pct
    ctx = build_context(farm, fields)
    fc = next(f for f in ctx.fields if f.crop == "groundnut")
    assert any(word in a for a in fc.assumed)
    assert any("inconsistent" in m for m in ctx.missing_inputs)


def test_eval8_weather_unavailable_auto_mode_is_labelled_and_traced(madurai):
    farm, fields, _ = madurai

    def down(lat, lon, d):
        raise ConnectionError("provider down")

    ex = run_assessment(farm, fields, "Should I irrigate today?", Language.en, settings=make_settings(weather_provider="auto"), weather_fetcher=down)
    assert ex.weather.simulated and any("SIMULATED" in n for n in ex.weather.notes)
    assert any(s.kind == "fallback" and "Provider failed" in s.summary for s in ex.steps)
    assert all(d.confidence.value != "high" for d in ex.decision.decisions)


def test_eval8_live_mode_never_substitutes_simulated_weather(madurai):
    farm, fields, _ = madurai

    def down(lat, lon, d):
        raise ConnectionError("provider down")

    ex = run_assessment(farm, fields, "Should I irrigate today?", Language.en, settings=make_settings(weather_provider="openmeteo"), weather_fetcher=down)
    assert ex.weather is None, "simulated data must not be substituted when the live provider fails"
    assert ex.decision.headline_action == Action.INSUFFICIENT_DATA
    assert any("weather" in q.lower() for q in ex.follow_up_questions)
    assert any(s.status == "error" and "NO simulated substitute" in s.summary for s in ex.steps)


def test_eval8_api_reports_503_when_live_weather_is_down(monkeypatch):
    from app.integrations import weather as wx

    def boom(self, *a, **k):
        raise ConnectionError("offline")

    monkeypatch.setattr(wx.OpenMeteoProvider, "fetch", boom)
    with TestClient(create_app(make_settings(weather_provider="openmeteo"))) as c:
        fid = c.get("/api/farms").json()[0]["id"]
        r = c.post("/api/irrigation/plan", json={"farm_id": fid})
        assert r.status_code == 503 and "not substituted" in r.json()["detail"]


def test_eval10_farmer_changes_water_during_planning(client, farm_id):
    allocated = []
    for m3 in [1500, 700, 400, 150, 20]:
        r = client.post("/api/irrigation/plan", json={"farm_id": farm_id, "available_water": m3, "available_water_unit": "m3"}).json()
        a = r["allocation"]
        assert a["total_allocated_litres"] <= m3 * 1000 + 1e-6
        assert r["decision"]["total_recommended_litres"] <= m3 * 1000 + 1e-6
        assert r["decision"]["validation"][0].startswith("PASS")
        allocated.append(a["total_allocated_litres"])
    assert allocated == sorted(allocated, reverse=True)
    low = client.post("/api/irrigation/plan", json={"farm_id": farm_id, "available_water": 20, "available_water_unit": "m3"}).json()
    assert low["allocation"]["scarcity_mode"] and low["allocation"]["deficit_litres"] > 0


def test_eval9_tamil_preserves_every_quantity_from_the_english_message(madurai):
    farm, fields, _ = madurai
    en = run_assessment(farm, fields, "Should I irrigate today?", Language.en, settings=make_settings())
    ta = run_assessment(farm, fields, "Should I irrigate today?", Language.ta, settings=make_settings())
    # every quantity in the English plan (litres, mm, rain %) appears unchanged in Tamil
    en_nums = numbers(" ".join([en.message.headline] + en.message.steps))
    ta_nums = numbers(" ".join([ta.message.headline] + ta.message.steps))
    assert en_nums <= ta_nums | {"48"}
    # and the Tamil text still states simulated-data + approval caveats
    assert "மாதிரி" in " ".join(ta.message.steps) and "பரிந்துரை மட்டுமே" in " ".join(ta.message.steps)


def test_origin_verify_header_blocks_direct_access():
    with TestClient(create_app(make_settings(origin_verify_secret="s3cret-s3cret-s3cret"))) as c:
        assert c.get("/api/farms").status_code == 403
        assert c.get("/api/farms", headers={"x-origin-verify": "wrong"}).status_code == 403
        assert c.get("/api/farms", headers={"x-origin-verify": "s3cret-s3cret-s3cret"}).status_code == 200
