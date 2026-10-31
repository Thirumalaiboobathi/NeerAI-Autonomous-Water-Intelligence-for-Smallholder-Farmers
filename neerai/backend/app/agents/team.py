"""The NeerAI agent team: one orchestrator Strands Agent that delegates to seven specialist Strands Agents.

Pattern: "agents as tools". Each specialist is a real `strands.Agent` with its own system prompt, its own deterministic
tools and its own trace hook. The orchestrator's tools are the specialists, so delegation, tool selection and result
hand-off all go through the Strands event loop. In demo mode the model is `ScriptedModel`; in AWS mode it is Bedrock.
"""
from __future__ import annotations

import json

from strands import Agent, tool

from . import tools as T
from .models import Call, Policy, Say, ScriptedModel, bedrock_model
from .runctx import SPECIALIST_TOOL_NAMES, RunContext, TraceHook
from .steps import insufficient

ROLE_LABEL = {
    "farm_context": "Farm Context Agent",
    "weather": "Weather Intelligence Agent",
    "crop_water": "Crop Water Intelligence Agent",
    "water_budget": "Water Budget & Allocation Agent",
    "decision": "Irrigation Decision Agent",
    "scenario": "Scenario Simulation Agent",
    "communication": "Tamil Farmer Communication Agent",
}

_COMMON = (
    "You are part of NeerAI, an irrigation decision-support team for smallholder farmers in Tamil Nadu, India. "
    "NEVER calculate agricultural numbers yourself: call your tools and report only numbers they return. "
    "Never invent weather data. Be concise and state assumptions and uncertainty. The farmer makes the final decision. "
    "You MUST call your tools to do your job; never answer from memory, never ask the farmer questions yourself, and never "
    "write <thinking> tags. Reply with one or two plain sentences after the tools finish."
)

ROLE_PROMPT = {
    "farm_context": _COMMON + " Role: Farm Context Agent. Call load_farm_context to retrieve the farm, fields and water. "
    "If the request says the farmer stated a water volume (e.g. 400 m3 or 3,000 litres), you MUST then call set_available_water "
    "with that number and unit ('m3' or 'litres'). Report any missing inputs.",
    "weather": _COMMON + " Role: Weather Intelligence Agent. Call fetch_weather_forecast, then analyze_weather_risks. "
    "Report rain probability, expected rain, heat risk, confidence and whether data is simulated.",
    "crop_water": _COMMON + " Role: Crop Water Intelligence Agent. Call compute_crop_water_requirements and explain "
    "ETc = Kc x ET0, depletion and efficiency assumptions per field.",
    "water_budget": _COMMON + " Role: Water Budget & Allocation Agent. Call set_field_priority ONLY if the request explicitly asks to prioritise a named field (never invent field names), then call "
    "allocate_water_budget (you MUST call allocate_water_budget; it takes no arguments). Explain which fields are prioritised and the unmet demand. You must not allocate numerically yourself.",
    "decision": _COMMON + " Role: Irrigation Decision Agent. Call generate_irrigation_decision then validate_irrigation_decision. "
    "Summarise the action per field, timing, confidence and what would change the recommendation.",
    "scenario": _COMMON + " Role: Scenario Simulation Agent. Call simulate_scenarios with the requested scenarios and explain "
    "trade-offs using only the returned numbers. State that scenarios are hypothetical.",
    "communication": _COMMON + " Role: Tamil Farmer Communication Agent. Call compose_farmer_message in the farmer's language "
    "(ta or en). You MUST call compose_farmer_message exactly once, with language 'ta' if the request says language: ta, else 'en'. "
    "Use very simple words and keep numbers, units and crop names exactly as returned.",
}

ORCHESTRATOR_PROMPT = (
    _COMMON + " Role: Orchestrator. You coordinate specialist agents by calling them as tools, in this order unless the plan says "
    "otherwise: farm_context_specialist, weather_specialist, crop_water_specialist, water_budget_specialist, decision_specialist, "
    "then scenario_specialist if what-if analysis is needed, and finally communication_specialist. Call EVERY specialist in the "
    "suggested plan, one at a time, passing the farmer's full request (including any stated water volume) as `request`. Only "
    "if farm_context reports blocking missing inputs may you stop and ask the farmer for them. After the specialists finish, reply "
    "with 2-3 plain sentences for the farmer that quote their numbers exactly, with no <thinking> tags."
)


def _tools_for(role: str, rc: RunContext) -> list:
    return {
        "farm_context": T.farm_context_tools, "weather": T.weather_tools, "crop_water": T.crop_water_tools,
        "water_budget": T.water_budget_tools, "decision": T.decision_tools, "scenario": T.scenario_tools,
        "communication": T.communication_tools,
    }[role](rc)


def _summary_of(last: str) -> str:
    try:
        d = json.loads(last)
        return str(d.get("summary", last))
    except (ValueError, TypeError, AttributeError):
        return last[:300]


def specialist_policy(role: str, rc: RunContext) -> Policy:
    """Scripted 'reasoning' for demo mode: which tools this specialist calls, in order."""
    h = rc.settings.planning_horizon_days

    def calls() -> list[Call]:
        if role == "farm_context":
            c = [Call("load_farm_context", {})]
            if rc.parsed.stated_water_litres is not None:
                c.append(Call("set_available_water", {"volume": rc.parsed.stated_water_litres, "unit": "litres"}))
            return c
        if role == "weather":
            return [Call("fetch_weather_forecast", {"days": h}), Call("analyze_weather_risks", {})]
        if role == "crop_water":
            return [Call("compute_crop_water_requirements", {"horizon_days": h})]
        if role == "water_budget":
            names = {f.id: f.name for f in rc.fields}
            c = [Call("set_field_priority", {"field_name": names[fid], "multiplier": m})
                 for fid, m in rc.priority_overrides.items() if fid in names]
            return c + [Call("allocate_water_budget", {})]
        if role == "decision":
            return [Call("generate_irrigation_decision", {}), Call("validate_irrigation_decision", {})]
        if role == "scenario":
            return [Call("simulate_scenarios", {"scenario_names": rc.parsed.scenarios or ["unexpected_rain"],
                                                "delay_days": max(rc.parsed.delay_days, 1)})]
        return [Call("compose_farmer_message", {"language": rc.language.value})]

    def policy(n: int, last: str):
        seq = calls()
        return seq[n] if n < len(seq) else Say(f"{ROLE_LABEL[role]}: {_summary_of(last)}")

    return policy


def build_specialist(role: str, rc: RunContext) -> Agent:
    s = rc.settings
    model = ScriptedModel(specialist_policy(role, rc), f"scripted-{role}") if s.agent_mode == "demo" else bedrock_model(s)
    return Agent(
        model=model, system_prompt=ROLE_PROMPT[role], tools=_tools_for(role, rc), name=ROLE_LABEL[role],
        description=f"NeerAI {ROLE_LABEL[role]}", callback_handler=None,
        hooks=[TraceHook(rc, ROLE_LABEL[role], s.agent_max_tool_calls)],
    )


def _delegate(rc: RunContext, role: str, request: str) -> str:
    last: Exception | None = None
    for attempt in range(rc.settings.agent_max_retries + 1):
        try:
            result = build_specialist(role, rc)(request)
            return json.dumps({"summary": f"{ROLE_LABEL[role]} completed", "report": str(result).strip()[:1200]}, ensure_ascii=False)
        except Exception as e:  # noqa: BLE001 - retry, then surface as a tool error to the orchestrator
            last = e
            rc.record(ROLE_LABEL[role], None, "fallback", "error", f"attempt {attempt + 1} failed: {type(e).__name__}")
    raise RuntimeError(f"{ROLE_LABEL[role]} failed after retries: {type(last).__name__}: {last}")


def specialist_tools(rc: RunContext) -> list:
    @tool
    def farm_context_specialist(request: str) -> str:
        """Delegate to the Farm Context Agent: load farm/field/crop/soil/water context, normalise units, find missing inputs."""
        return _delegate(rc, "farm_context", request)

    @tool
    def weather_specialist(request: str) -> str:
        """Delegate to the Weather Intelligence Agent: forecast, rain probability, heat risk and forecast confidence."""
        return _delegate(rc, "weather", request)

    @tool
    def crop_water_specialist(request: str) -> str:
        """Delegate to the Crop Water Intelligence Agent: FAO-56 crop water requirement per field."""
        return _delegate(rc, "crop_water", request)

    @tool
    def water_budget_specialist(request: str) -> str:
        """Delegate to the Water Budget & Allocation Agent: allocate limited water across fields by priority."""
        return _delegate(rc, "water_budget", request)

    @tool
    def decision_specialist(request: str) -> str:
        """Delegate to the Irrigation Decision Agent: irrigate now, delay, partial or prioritise, with reasoning."""
        return _delegate(rc, "decision", request)

    @tool
    def scenario_specialist(request: str) -> str:
        """Delegate to the Scenario Simulation Agent: what-if comparisons (shortage, rain, heat, delay)."""
        return _delegate(rc, "scenario", request)

    @tool
    def communication_specialist(request: str) -> str:
        """Delegate to the Tamil Farmer Communication Agent: simple Tamil or English farmer message."""
        return _delegate(rc, "communication", request)

    return [farm_context_specialist, weather_specialist, crop_water_specialist, water_budget_specialist,
            decision_specialist, scenario_specialist, communication_specialist]


def orchestrator_policy(rc: RunContext) -> Policy:
    seq = rc.parsed.steps

    def policy(n: int, last: str):
        if n > 0 and seq[n - 1] == "farm_context" and rc.ctx and rc.ctx.blocking_missing:
            return Say("I need more information before I can plan: " + " ".join(insufficient(rc)))
        if n < len(seq):
            return Call(f"{seq[n]}_specialist", {"request": f"{rc.query} (intent: {rc.parsed.intent}; language: {rc.language.value})"})
        return Say(rc.answer or "Assessment complete.")

    return policy


def build_orchestrator(rc: RunContext) -> Agent:
    s = rc.settings
    model = ScriptedModel(orchestrator_policy(rc), "scripted-orchestrator") if s.agent_mode == "demo" else bedrock_model(s)
    return Agent(
        model=model, system_prompt=ORCHESTRATOR_PROMPT, tools=specialist_tools(rc), name="NeerAI Orchestrator",
        description="Coordinates NeerAI specialist agents", callback_handler=None,
        hooks=[TraceHook(rc, "Orchestrator", s.agent_max_tool_calls)],
    )


def orchestrator_brief(rc: RunContext) -> str:
    p = rc.parsed
    plan = " -> ".join(f"{x}_specialist" for x in p.steps)
    extra = f" Farmer stated {p.stated_water_litres:,.0f} L of water." if p.stated_water_litres else ""
    return (f"Farmer request: {rc.query!r}. Detected intent: {p.intent}. Reply language: {rc.language.value}.{extra} "
            f"Suggested plan: {plan}. Farm: {rc.farm.farm_name} ({rc.farm.district}).")


assert set(SPECIALIST_TOOL_NAMES) == {f"{k}_specialist" for k in ROLE_LABEL}
