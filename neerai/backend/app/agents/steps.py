"""Deterministic pipeline steps. Strands tools wrap these; the orchestrator's fallback reconciler calls them directly."""
from __future__ import annotations

import time

from ..calculations import scenarios as sc
from ..calculations.decision import decide_all, validate_decision
from ..calculations.pipeline import build_context, compute_allocation, compute_crop_water
from ..calculations.units import to_litres
from ..integrations import weather as wx
from . import messages
from .runctx import RunContext


def need(value, label: str):
    if value is None:
        raise ValueError(f"{label} is not available yet - run the preceding specialist first")
    return value


def do_context(rc: RunContext) -> dict:
    rc.ctx = build_context(rc.farm, rc.fields)
    c = rc.ctx
    if rc.available_override_litres is not None:
        c.blocking_missing = [m for m in c.blocking_missing if "water volume" not in m]
        c.water_available_litres = rc.available_override_litres
    return {
        "summary": (f"{len(c.fields)} field(s), {c.total_area_ha} ha, water {c.water_available_litres} L"
                    f"{' (stated by farmer)' if rc.available_override_litres is not None else ''}; "
                    f"missing: {len(c.missing_inputs)}, blocking: {len(c.blocking_missing)}"),
        "fields": [{"name": f.name, "crop": f.crop, "stage": f.stage.value, "area_ha": f.area_ha, "soil": f.soil_type,
                    "method": f.irrigation_method, "efficiency": f.efficiency, "assumed": f.assumed} for f in c.fields],
        "water_available_litres": rc.available_litres,
        "missing_inputs": c.missing_inputs, "blocking_missing": c.blocking_missing,
    }


def do_set_water(rc: RunContext, volume: float, unit: str) -> dict:
    litres = to_litres(volume, unit)
    rc.available_override_litres = litres
    if rc.ctx:
        rc.ctx.blocking_missing = [m for m in rc.ctx.blocking_missing if "water volume" not in m]
    return {"summary": f"Available water set to {litres:,.0f} L (from {volume:g} {unit})", "available_litres": litres}


def do_weather(rc: RunContext, days: int) -> dict:
    ctx = need(rc.ctx, "farm context")
    s = rc.settings
    scenario = rc.weather_scenario or s.weather_scenario
    attempts = max(1, s.agent_max_retries + 1)
    last: Exception | None = None
    for _ in range(attempts):
        try:
            if rc.weather_fetcher:
                rc.weather = rc.weather_fetcher(ctx.latitude, ctx.longitude, days)
            else:
                rc.weather = wx.get_weather(s.weather_provider, ctx.latitude, ctx.longitude, days, scenario, s.weather_timeout_s)
            last = None
            break
        except Exception as e:  # provider failure: retry, then fall back to a labelled simulation
            last = e
    fell_back = False
    if last is not None and s.weather_provider == "openmeteo":
        ctx.blocking_missing.append("Live weather forecast unavailable; simulated data is not substituted in live mode")
        rc.record("Weather Intelligence Agent", "fetch_weather_forecast", "fallback", "error",
                  f"Live provider failed after {attempts} attempt(s) ({type(last).__name__}); NO simulated substitute in live mode")
        raise RuntimeError(f"live weather unavailable ({type(last).__name__}); not substituting simulated data")
    if last is not None:
        fell_back = True
        rc.weather = wx.get_weather("mock", ctx.latitude, ctx.longitude, days, scenario)
        rc.weather.notes.append(f"Weather provider failed ({type(last).__name__}); SIMULATED data used instead.")
        rc.record("Weather Intelligence Agent", "fetch_weather_forecast", "fallback", "fallback",
                  f"Provider failed after {attempts} attempt(s); using labelled simulated weather")
    w = rc.weather
    return {
        "summary": (f"{'FALLBACK: ' if fell_back else ''}{w.source}; rain 48h {w.rain_probability_48h_pct:.0f}% "
                    f"(~{w.expected_rain_48h_mm} mm), Tmax {w.max_temp_c:.0f} C, confidence {w.forecast_confidence.value}"),
        "source": w.source, "simulated": w.simulated, "rain_probability_48h_pct": w.rain_probability_48h_pct,
        "expected_rain_48h_mm": w.expected_rain_48h_mm, "avg_et0_mm_day": w.avg_et0_mm_day, "max_temp_c": w.max_temp_c,
        "forecast_confidence": w.forecast_confidence.value, "fallback_used": fell_back,
    }


def do_weather_risks(rc: RunContext) -> dict:
    w = need(rc.weather, "weather assessment")
    return {
        "summary": f"heat risk {w.heat_risk}; confidence {w.forecast_confidence.value}; {len(w.notes)} note(s)",
        "heat_risk": w.heat_risk, "forecast_confidence": w.forecast_confidence.value, "notes": w.notes,
        "daily": [{"date": str(d.date), "precip_mm": d.precip_mm, "prob_pct": d.precip_prob_pct, "tmax_c": d.tmax_c, "et0_mm": d.et0_mm}
                  for d in w.daily],
    }


def do_crop_water(rc: RunContext, horizon: int) -> dict:
    ctx, w = need(rc.ctx, "farm context"), need(rc.weather, "weather assessment")
    rc.crop_water = compute_crop_water(ctx, w, horizon)
    cw = rc.crop_water
    return {
        "summary": (f"demand {cw.total_demand_litres:,.0f} L total, {cw.total_due_demand_litres:,.0f} L due now across "
                    f"{sum(1 for n in cw.fields if n.due)} of {len(cw.fields)} field(s)"),
        "fields": [{"name": n.name, "kc": n.kc, "etc_mm_day": n.etc_mm_day, "depletion_mm": n.depletion_mm, "raw_mm": n.raw_mm,
                    "net_mm": n.net_requirement_mm, "gross_mm": n.gross_requirement_mm, "volume_litres": n.volume_litres,
                    "due": n.due, "defer_for_rain": n.defer_for_rain} for n in cw.fields],
    }


def do_set_priority(rc: RunContext, field_name: str, multiplier: float) -> dict:
    ctx = need(rc.ctx, "farm context")
    match = [f for f in ctx.fields if field_name.lower() in f.name.lower() or field_name.lower() == f.crop]
    if not match:
        raise ValueError(f"no field matches '{field_name}'. Fields: {', '.join(f.name for f in ctx.fields)}")
    rc.priority_overrides[match[0].field_id] = max(0.1, min(3.0, multiplier))
    return {"summary": f"Priority of {match[0].name} set to x{rc.priority_overrides[match[0].field_id]:g}"}


def do_allocate(rc: RunContext) -> dict:
    ctx, cw = need(rc.ctx, "farm context"), need(rc.crop_water, "crop water assessment")
    avail = rc.available_litres
    if avail is None:
        raise ValueError("available water volume is unknown - ask the farmer how much water is available")
    rc.allocation = compute_allocation(ctx, cw, avail, rc.priority_overrides)
    p = rc.allocation
    return {
        "summary": (f"{'SCARCITY: ' if p.scarcity_mode else ''}allocated {p.total_allocated_litres:,.0f} of {p.available_litres:,.0f} L "
                    f"available; demand {p.total_demand_litres:,.0f} L; deficit {p.deficit_litres:,.0f} L"),
        "scarcity_mode": p.scarcity_mode, "deficit_litres": p.deficit_litres,
        "allocations": [{"field": a.name, "rank": a.rank, "tier": a.tier, "demand": a.demand_litres,
                         "allocated": a.allocated_litres, "unmet": a.unmet_litres} for a in p.allocations],
    }


def do_decide(rc: RunContext) -> dict:
    ctx, w = need(rc.ctx, "farm context"), need(rc.weather, "weather assessment")
    cw, plan = need(rc.crop_water, "crop water assessment"), need(rc.allocation, "water allocation plan")
    rc.decision = decide_all(ctx, w, cw, plan)
    d = rc.decision
    return {
        "summary": f"{d.headline_action.value}: {d.summary}",
        "decisions": [{"field": x.field_name, "action": x.action.value, "volume_litres": x.recommended_volume_litres,
                       "confidence": x.confidence.value, "timing": x.timing} for x in d.decisions],
    }


def do_validate(rc: RunContext) -> dict:
    d, plan = need(rc.decision, "irrigation decision"), need(rc.allocation, "water allocation plan")
    d.validation = validate_decision(d, plan)
    ok = all(not f.startswith("FAIL") for f in d.validation)
    return {"summary": "; ".join(d.validation), "passed": ok, "findings": d.validation}


def do_scenarios(rc: RunContext, names: list[str], delay_days: int) -> dict:
    ctx, w = need(rc.ctx, "farm context"), need(rc.weather, "weather assessment")
    avail = rc.available_litres
    if avail is None:
        raise ValueError("available water volume is unknown")
    params = []
    for n in names:
        if n not in sc.PRESETS:
            raise ValueError(f"unknown scenario '{n}'. Options: {', '.join(sc.PRESETS)}")
        p = sc.PRESETS[n].model_copy(deep=True)
        if n == "delayed_irrigation" and delay_days > 0:
            p.delay_days = delay_days
            p.title = f"Irrigation delayed by {delay_days} day(s)"
        params.append(p)
    rc.scenarios = sc.compare(ctx, w, avail, params, rc.settings.planning_horizon_days)
    c = rc.scenarios
    return {
        "summary": "; ".join(f"{s.title}: demand {s.total_demand_litres:,.0f} L, deficit {s.deficit_litres:,.0f} L" for s in c.scenarios),
        "base": {"demand": c.base.total_demand_litres, "deficit": c.base.deficit_litres},
        "scenarios": [{"name": s.name, "demand": s.total_demand_litres, "allocated": s.total_allocated_litres,
                       "deficit": s.deficit_litres, "at_risk": s.at_risk_fields, "delta": s.delta_vs_base} for s in c.scenarios],
        "changed_actions": c.changed_actions,
    }


def do_message(rc: RunContext, language: str) -> dict:
    d, w = need(rc.decision, "irrigation decision"), need(rc.weather, "weather assessment")
    lang = rc.language  # the farmer's language is authoritative; an LLM-supplied `language` argument is ignored
    rc.message = messages.compose(d, w, rc.allocation, lang, rc.parsed.focus_crop, rc.scenarios)
    rc.answer = rc.message.short_summary
    return {"summary": f"{lang.value} message with {len(rc.message.steps)} steps", "headline": rc.message.headline, "steps": rc.message.steps}


def insufficient(rc: RunContext) -> list[str]:
    """Questions to ask the farmer when essential inputs are missing."""
    qs = []
    c = rc.ctx
    if c is None:
        return ["Which farm and field should I plan for?"]
    for m in c.blocking_missing:
        if "weather" in m.lower():
            qs.append("The live weather service is unavailable right now. Please try again shortly; NeerAI will not guess the weather.")
        elif "water volume" in m:
            qs.append("How much water do you have available for irrigation (in litres or cubic metres)?")
        elif "No fields" in m:
            qs.append("Please add a field with its crop, area and growth stage.")
        else:
            qs.append(f"Please fix: {m}")
    return qs


def timed(fn, *a, **k):
    t = time.perf_counter()
    out = fn(*a, **k)
    return out, int((time.perf_counter() - t) * 1000)
