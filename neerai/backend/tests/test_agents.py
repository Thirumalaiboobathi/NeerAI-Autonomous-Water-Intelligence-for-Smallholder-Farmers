"""Multi-agent workflow tests: real Strands Agents with the scripted model provider (no AWS needed)."""
import re

import pytest
from strands import Agent

from app.agents import messages, orchestrator
from app.agents.intent import parse_query
from app.agents.models import bedrock_model
from app.agents.orchestrator import run_assessment, select_answer
from app.agents.runctx import RunContext
from app.agents.team import build_orchestrator
from app.core.config import Settings
from app.schemas.domain import Action, Language
from app.services.demo_seed import build_demo
from tests.conftest import make_settings

TAMIL = re.compile(r"[஀-௿]")


@pytest.fixture()
def demo():
    return build_demo("madurai")


def run(demo, q, lang=Language.en, **kw):
    farm, fields = demo
    return run_assessment(farm, fields, q, lang, settings=kw.pop("settings", make_settings()), **kw)


def tools_used(ex):
    return [s.tool for s in ex.steps if s.tool and s.kind in ("tool", "agent")]


# ── real Strands orchestration ──
def test_orchestrator_is_a_strands_agent_with_specialist_tools(demo):
    farm, fields = demo
    rc = RunContext(settings=make_settings(), farm=farm, fields=fields, query="q", parsed=parse_query("q"), language=Language.en)
    agent = build_orchestrator(rc)
    assert isinstance(agent, Agent)
    names = set(agent.tool_names)
    assert {"farm_context_specialist", "weather_specialist", "crop_water_specialist", "water_budget_specialist",
            "decision_specialist", "scenario_specialist", "communication_specialist"} <= names


def test_full_assessment_uses_every_required_agent_and_tool_in_order(demo):
    ex = run(demo, "Should I irrigate my paddy field today?")
    used = tools_used(ex)
    for t in ["farm_context_specialist", "load_farm_context", "weather_specialist", "fetch_weather_forecast",
              "crop_water_specialist", "compute_crop_water_requirements", "water_budget_specialist", "allocate_water_budget",
              "decision_specialist", "generate_irrigation_decision", "validate_irrigation_decision",
              "communication_specialist", "compose_farmer_message"]:
        assert t in used, t
    order = [used.index(t) for t in ["load_farm_context", "fetch_weather_forecast", "compute_crop_water_requirements",
                                       "allocate_water_budget", "generate_irrigation_decision", "compose_farmer_message"]]
    assert order == sorted(order)
    assert ex.status == "completed" and not ex.errors
    assert all(s.status == "ok" for s in ex.steps)
    assert [s.seq for s in ex.steps] == list(range(1, len(ex.steps) + 1))


def test_trace_hides_secrets_and_has_timings(demo):
    ex = run(demo, "Should I irrigate today?")
    blob = ex.model_dump_json()
    assert "AKIA" not in blob and "secret" not in blob.lower()
    assert all(s.duration_ms >= 0 and s.started_at for s in ex.steps)


def test_results_are_typed_schemas(demo):
    ex = run(demo, "Should I irrigate today?")
    assert ex.context and ex.weather and ex.crop_water and ex.allocation and ex.decision and ex.message
    assert ex.decision.requires_farmer_approval


# ── water constraints & scarcity ──
def test_stated_water_is_parsed_converted_and_respected(demo):
    ex = run(demo, "I have only 400 m3 of water. Which field should I prioritize?")
    assert "set_available_water" in tools_used(ex)
    assert ex.allocation.available_litres == 400_000
    assert ex.allocation.total_allocated_litres <= 400_000
    assert ex.allocation.scarcity_mode
    assert ex.decision.total_recommended_litres <= 400_000
    assert Action.PRIORITIZE_FIELD in {d.action for d in ex.decision.decisions}


def test_tiny_water_amount_in_litres(demo):
    ex = run(demo, "I have only 3,000 litres of water. Which field should I prioritize?")
    assert ex.allocation.available_litres == 3000
    assert ex.allocation.total_allocated_litres <= 3000


def test_priority_overrides_reach_the_allocation_tool(demo):
    farm, fields = demo
    paddy = next(f for f in fields if f.crop == "paddy")
    base = run(demo, "plan", available_litres=300_000)
    pinned = run(demo, "plan", available_litres=300_000, priority_overrides={paddy.id: 3.0})
    got = lambda ex: next(a.allocated_litres for a in ex.allocation.allocations if a.crop == "paddy")  # noqa: E731
    assert got(pinned) > got(base)
    assert "set_field_priority" in tools_used(pinned)


# ── missing inputs ──
def test_missing_water_asks_instead_of_guessing(demo):
    farm, fields = demo
    farm.water_available_litres = None
    ex = run((farm, fields), "Should I irrigate today?")
    assert ex.decision.headline_action == Action.INSUFFICIENT_DATA
    assert ex.allocation is None and ex.follow_up_questions
    assert any("water" in q.lower() for q in ex.follow_up_questions)
    assert ex.status == "partial"
    assert "allocate_water_budget" not in tools_used(ex)


def test_missing_soil_and_method_become_stated_assumptions(demo):
    farm, fields = demo
    fields[0].soil_type = None
    fields[0].irrigation_method = None
    ex = run((farm, fields), "Should I irrigate today?")
    assert any("Soil type not given" in a for a in ex.context.fields[0].assumed)
    assert ex.context.missing_inputs


# ── intents / scenarios ──
def test_delay_question_runs_scenario_agent(demo):
    ex = run(demo, "What happens if I delay irrigation by one day?")
    assert ex.intent == "delay_scenario"
    assert "scenario_specialist" in tools_used(ex) and "simulate_scenarios" in tools_used(ex)
    assert ex.scenarios and ex.scenarios.scenarios[0].name == "delayed_irrigation"


def test_rain_question_compares_rain_vs_dry(demo):
    ex = run(demo, "Will tomorrow's rain affect my irrigation plan?")
    assert {s.name for s in ex.scenarios.scenarios} == {"unexpected_rain", "dry_spell"}


# ── weather honesty & failure handling ──
def test_demo_weather_is_never_presented_as_live(demo):
    ex = run(demo, "Should I irrigate today?")
    assert ex.weather.simulated
    assert any("SIMULATED" in s for s in ex.data_sources)


def test_weather_provider_failure_falls_back_to_labelled_simulation(demo):
    def broken(lat, lon, days):
        raise TimeoutError("provider down")

    ex = run(demo, "Should I irrigate today?", weather_fetcher=broken)
    assert ex.decision is not None
    assert ex.weather.simulated and any("failed" in n for n in ex.weather.notes)
    assert any(s.kind == "fallback" for s in ex.steps)


def test_orchestrator_crash_is_recovered_by_deterministic_fallback(demo, monkeypatch):
    def boom(rc):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(orchestrator, "build_orchestrator", boom)
    ex = run(demo, "Should I irrigate today?")
    assert ex.decision and ex.allocation and ex.message
    assert ex.allocation.total_allocated_litres <= ex.allocation.available_litres
    assert any(s.kind == "fallback" for s in ex.steps) and any("orchestrator" in e for e in ex.errors)


def test_tool_execution_limit_cancels_runaway_loops(demo):
    ex = run(demo, "Should I irrigate today?", settings=make_settings(agent_max_tool_calls=3))
    assert any(s.status == "error" for s in ex.steps)
    assert ex.decision is not None  # reconciled


# ── Tamil ──
def test_tamil_request_returns_tamil_with_exact_numbers(demo):
    ex = run(demo, "Explain my water plan in Tamil.")
    assert ex.language == Language.ta and ex.message.language == Language.ta
    assert TAMIL.search(ex.answer)
    assert "லிட்டர்" in ex.message.headline
    allowed = messages.collect_numbers([ex.decision, ex.allocation, ex.weather])
    assert messages.numbers_consistent(" ".join([ex.message.headline] + ex.message.steps), allowed)
    assert ex.message.voice_text and "(" not in ex.message.voice_text


def test_tamil_message_states_simulated_weather_and_approval(demo):
    ex = run(demo, "Explain my water plan in Tamil.")
    text = " ".join(ex.message.steps)
    assert "மாதிரி" in text and "பரிந்துரை மட்டுமே" in text


def test_tamil_script_in_query_selects_tamil(demo):
    assert parse_query("இன்று நீர்ப்பாசனம் செய்யலாமா?").language == Language.ta


# ── intent / number guard units ──
@pytest.mark.parametrize("q,litres", [("only 3,000 litres", 3000), ("I have 400 m3", 400_000), ("2.5 kl left", 2500),
                                      ("5000 லிட்டர் தண்ணீர்", 5000), ("no number here", None)])
def test_volume_parsing(q, litres):
    assert parse_query(q).stated_water_litres == litres


def test_number_guard_accepts_tool_numbers_and_rejects_invented(demo):
    ex = run(demo, "Should I irrigate today?")
    allowed = messages.collect_numbers([ex.decision, ex.allocation, ex.weather])
    ok = f"Use {ex.allocation.total_allocated_litres:,.0f} L today."
    assert messages.numbers_consistent(ok, allowed)
    assert not messages.numbers_consistent("Use 123456 L today.", allowed)
    assert not messages.numbers_consistent("Rain chance is 97%.", allowed)


def test_bedrock_mode_rejects_llm_narrative_with_fabricated_quantities(demo):
    ex = run(demo, "Should I irrigate today?")
    farm, fields = demo
    rc = RunContext(settings=make_settings(agent_mode="bedrock"), farm=farm, fields=fields, query="q", parsed=parse_query("q"),
                    language=Language.en)
    rc.ctx, rc.weather, rc.crop_water, rc.allocation, rc.decision, rc.message = (
        ex.context, ex.weather, ex.crop_water, ex.allocation, ex.decision, ex.message)
    bad = select_answer(rc, "Irrigate with 987654 L now.", blocked=False)
    assert bad == ex.message.short_summary
    good = select_answer(rc, f"Apply {ex.allocation.total_allocated_litres:,.0f} L.", blocked=False)
    assert good.startswith("Apply")


def test_bedrock_model_factory_builds_without_network():
    m = bedrock_model(Settings(agent_mode="bedrock"))
    assert m.get_config()["model_id"] == "apac.amazon.nova-pro-v1:0"
