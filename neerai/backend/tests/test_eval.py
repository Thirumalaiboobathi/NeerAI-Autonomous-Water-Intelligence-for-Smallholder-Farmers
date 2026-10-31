"""Deterministic agent evaluation: every case checks tool use, water constraints, honesty and language - no LLM judge."""
import json
import re
from pathlib import Path

import pytest

from app.agents import messages
from app.agents.orchestrator import run_assessment
from app.schemas.domain import Language
from app.services.demo_seed import build_demo
from tests.conftest import make_settings

CASES = json.loads((Path(__file__).parent / "eval" / "scenarios.json").read_text(encoding="utf-8"))
TAMIL = re.compile(r"[஀-௿]")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_eval_case(case):
    farm, fields = build_demo("madurai")
    if "water_litres" in case:
        farm.water_available_litres = case["water_litres"]
    ex = run_assessment(farm, fields, case["query"], Language.en, settings=make_settings(weather_scenario=case["weather"]))
    e = case["expect"]
    used = {s.tool for s in ex.steps}

    for t in e.get("tools", []):
        assert t in used, f"agent did not use tool {t}"
    if e.get("budget_respected") and ex.allocation:
        assert ex.allocation.total_allocated_litres <= ex.allocation.available_litres + 1e-6
        assert ex.decision.total_recommended_litres <= ex.allocation.available_litres + 1e-6
    if "available_litres" in e:
        assert ex.allocation.available_litres == e["available_litres"]
    if "scarcity" in e:
        assert ex.allocation.scarcity_mode is e["scarcity"]
    if e.get("weather_labelled_simulated"):
        assert ex.weather.simulated and any("SIMULATED" in s for s in ex.data_sources)
    if "language" in e:
        assert ex.language.value == e["language"]
    if e.get("tamil_text"):
        assert TAMIL.search(ex.answer)
    if e.get("numbers_consistent"):
        allowed = messages.collect_numbers([ex.decision, ex.allocation, ex.weather])
        assert messages.numbers_consistent(" ".join(ex.message.steps) + ex.message.headline, allowed)
    if "heat_risk" in e:
        assert ex.weather.heat_risk == e["heat_risk"]
    if "headline_action" in e:
        assert ex.decision.headline_action.value == e["headline_action"]
    if e.get("asks_question"):
        assert ex.follow_up_questions
    if e.get("no_allocation"):
        assert ex.allocation is None
    if "has_action" in e:
        assert e["has_action"] in {d.action.value for d in ex.decision.decisions}
    for crop, allowed_actions in e.get("actions", {}).items():
        d = next(d for d in ex.decision.decisions if d.crop == crop)
        assert d.action.value in allowed_actions, f"{crop}: {d.action.value} not in {allowed_actions}"
    if "scenario_names" in e:
        assert {s.name for s in ex.scenarios.scenarios} == set(e["scenario_names"])
    # universal properties
    assert ex.mode == "demo"
    if ex.decision and ex.decision.decisions:
        assert ex.decision.requires_farmer_approval
        assert all(d.reasoning and d.would_change_if for d in ex.decision.decisions)
    assert [s.seq for s in ex.steps] == sorted(s.seq for s in ex.steps)
