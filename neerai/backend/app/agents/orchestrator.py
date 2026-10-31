"""Runs the NeerAI multi-agent workflow end to end and assembles the AgentExecution record."""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

from ..core.config import Settings, get_settings
from ..schemas.domain import (
    Action, AgentExecution, Confidence, Farm, Field_, Language, OverallDecision,
)
from . import messages, steps
from .intent import ParsedQuery, parse_query
from .runctx import RunContext
from .team import build_orchestrator, orchestrator_brief

log = logging.getLogger("neerai.orchestrator")

_HAVE = {
    "farm_context": lambda rc: rc.ctx, "weather": lambda rc: rc.weather, "crop_water": lambda rc: rc.crop_water,
    "water_budget": lambda rc: rc.allocation, "decision": lambda rc: rc.decision, "scenario": lambda rc: rc.scenarios,
    "communication": lambda rc: rc.message,
}
_FALLBACK_AGENT = {
    "farm_context": "Farm Context Agent", "weather": "Weather Intelligence Agent", "crop_water": "Crop Water Intelligence Agent",
    "water_budget": "Water Budget & Allocation Agent", "decision": "Irrigation Decision Agent",
    "scenario": "Scenario Simulation Agent", "communication": "Tamil Farmer Communication Agent",
}


def _run_step(rc: RunContext, step: str) -> None:
    h = rc.settings.planning_horizon_days
    if step == "farm_context":
        steps.do_context(rc)
        if rc.parsed.stated_water_litres is not None:
            steps.do_set_water(rc, rc.parsed.stated_water_litres, "litres")
    elif step == "weather":
        steps.do_weather(rc, h)
    elif step == "crop_water":
        steps.do_crop_water(rc, h)
    elif step == "water_budget":
        steps.do_allocate(rc)
    elif step == "decision":
        steps.do_decide(rc)
        steps.do_validate(rc)
    elif step == "scenario":
        steps.do_scenarios(rc, rc.parsed.scenarios or ["unexpected_rain"], max(rc.parsed.delay_days, 1))
    elif step == "communication":
        steps.do_message(rc, rc.language.value)


def enforce_stated_water(rc: RunContext) -> None:
    """The farmer's stated water volume is a hard input: if the LLM skipped `set_available_water`, apply it now and
    discard any results computed with a different budget so they are recomputed (traced as a fallback)."""
    want = rc.parsed.stated_water_litres
    if want is None or rc.ctx is None or rc.available_override_litres == want:
        return
    steps.do_set_water(rc, want, "litres")
    rc.allocation = rc.decision = rc.message = rc.scenarios = None
    rc.record("Farm Context Agent", "fallback:set_available_water", "fallback", "fallback",
              f"Agent loop did not apply the farmer's stated water ({want:,.0f} L); applied deterministically and recomputed dependents")


def reconcile(rc: RunContext) -> None:
    """Graceful degradation: if the agent loop did not produce a required result, compute it deterministically (traced)."""
    enforce_stated_water(rc)
    for step in rc.parsed.steps:
        if _HAVE[step](rc) is not None:
            continue
        if step != "farm_context" and rc.ctx is not None and rc.ctx.blocking_missing:
            break
        t0 = time.perf_counter()
        try:
            _run_step(rc, step)
            rc.record(_FALLBACK_AGENT[step], f"fallback:{step}", "fallback", "fallback",
                      "Result missing after agent loop; computed directly by the deterministic engine",
                      int((time.perf_counter() - t0) * 1000))
        except Exception as e:  # noqa: BLE001
            rc.record(_FALLBACK_AGENT[step], f"fallback:{step}", "fallback", "error", f"{type(e).__name__}: {e}")
            rc.errors.append(f"{step}: {e}")
            break
    if rc.decision is not None and not rc.decision.validation and rc.allocation is not None:
        steps.do_validate(rc)


def _insufficient_decision(rc: RunContext) -> OverallDecision:
    return OverallDecision(
        headline_action=Action.INSUFFICIENT_DATA, summary="More information is needed before NeerAI can recommend irrigation.",
        total_recommended_litres=0, available_litres=rc.available_litres or 0, scarcity_mode=False, decisions=[],
        validation=["Essential inputs missing: " + "; ".join(rc.ctx.blocking_missing if rc.ctx else ["farm context unavailable"])],
    )


def build_prompt_hints(rc: RunContext) -> str:
    return orchestrator_brief(rc)


_TAGS = re.compile(r"<(thinking|reasoning)>.*?</(thinking|reasoning)>|</?(thinking|reasoning)>", re.DOTALL | re.IGNORECASE)


def clean_llm_text(text: str) -> str:
    """Remove model scratchpad tags that must never reach a farmer."""
    return _TAGS.sub("", text).strip()


def select_answer(rc: RunContext, llm_text: str, blocked: bool) -> str:
    """Template answer built from verified numbers. In Bedrock mode the LLM narrative is used only if it is clean, states at
    least one quantity, and every quantity traces back to tool outputs."""
    template = rc.message.short_summary if rc.message else ""
    if rc.settings.agent_mode == "bedrock" and llm_text and not blocked and rc.decision:
        text = clean_llm_text(llm_text)
        allowed = messages.collect_numbers([rc.ctx, rc.weather, rc.crop_water, rc.allocation, rc.decision, rc.scenarios])
        if text and "<" not in text and messages.states_quantity(text) and messages.numbers_consistent(text, allowed):
            rc.record("Orchestrator", "number_guard", "validation", "ok", "LLM narrative accepted: quantities match tool outputs")
            return text
        rc.record("Orchestrator", "number_guard", "validation", "fallback",
                  "LLM narrative rejected (scratchpad text, no verified quantity, or unverified quantity); template answer used")
    return template


def run_assessment(
    farm: Farm, fields: list[Field_], query: str, language: Language = Language.en, *,
    settings: Optional[Settings] = None, available_litres: Optional[float] = None, priority_overrides: Optional[dict[str, float]] = None,
    weather_scenario: Optional[str] = None, weather_fetcher=None, intent_hint: Optional[str] = None, parsed: Optional[ParsedQuery] = None,
) -> AgentExecution:
    settings = settings or get_settings()
    parsed = parsed or parse_query(query, language)
    if intent_hint:
        parsed.intent = intent_hint
    lang = parsed.language
    rc = RunContext(
        settings=settings, farm=farm, fields=fields, query=query, parsed=parsed, language=lang,
        available_override_litres=available_litres, priority_overrides=dict(priority_overrides or {}),
        weather_scenario=weather_scenario, weather_fetcher=weather_fetcher,
    )
    t0 = time.perf_counter()
    llm_text = ""
    try:
        result = build_orchestrator(rc)(build_prompt_hints(rc))
        llm_text = str(result).strip()
    except Exception as e:  # noqa: BLE001 - never lose the request: fall through to deterministic reconciliation
        log.warning("orchestrator failed: %s", type(e).__name__)
        rc.errors.append(f"orchestrator: {type(e).__name__}")
        rc.record("Orchestrator", None, "fallback", "error", f"Agent loop failed ({type(e).__name__}); using deterministic fallback")
    reconcile(rc)

    blocked = bool(rc.ctx and rc.ctx.blocking_missing)
    questions = steps.insufficient(rc) if blocked else []
    decision = rc.decision or (_insufficient_decision(rc) if blocked else None)

    answer = select_answer(rc, llm_text, blocked)
    if blocked:
        answer = " ".join(questions) if lang == Language.en else "மேலும் தகவல் தேவை: " + " ".join(questions)

    rc.steps.sort(key=lambda s: s.started_at)
    for i, s in enumerate(rc.steps, 1):
        s.seq = i

    sources = ["Farm profile (user entered / demo sample)", "Crop & soil parameters: sample FAO-56-based values (configurable)"]
    if rc.weather:
        sources.append(f"Weather: {rc.weather.source}{' - SIMULATED' if rc.weather.simulated else ''}")
    follow = []
    if decision and decision.headline_action != Action.INSUFFICIENT_DATA:
        follow = ["What happens if I delay irrigation by one day?", "Explain my water plan in Tamil.",
                  "What if I have only 60% of this water?"]
    missing = [x for x in parsed.steps if _HAVE[x](rc) is None]
    status = "completed" if (decision and not missing and not blocked) else "partial"
    if decision is None:
        status = "failed"
    low_conf = decision and any(d.confidence == Confidence.low for d in decision.decisions)
    if low_conf:
        sources.append("Note: some decisions are low-confidence (simulated/uncertain weather or defaulted inputs)")

    return AgentExecution(
        farm_id=farm.id, query=query, language=lang, intent=parsed.intent, mode=settings.agent_mode, status=status,
        duration_ms=int((time.perf_counter() - t0) * 1000), steps=rc.steps, context=rc.ctx, weather=rc.weather,
        crop_water=rc.crop_water, allocation=rc.allocation, decision=decision, scenarios=rc.scenarios, message=rc.message,
        answer=answer, data_sources=sources, follow_up_questions=questions or follow, errors=rc.errors,
    )
