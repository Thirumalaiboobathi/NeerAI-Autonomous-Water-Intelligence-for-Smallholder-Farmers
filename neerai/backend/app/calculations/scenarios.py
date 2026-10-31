"""Deterministic what-if simulation. Scenario weather/water values are hypothetical inputs, never forecasts."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from ..schemas.domain import (
    Action, FarmContext, ScenarioComparison, ScenarioResult, WeatherAssessment,
)
from ..integrations.weather import assess
from . import reference as ref
from .pipeline import run_core

ET0_PER_DEG_C = 0.03  # documented heuristic: +3% reference ET per +1 C (simplified; FAO-56 Penman-Monteith is nonlinear)


class ScenarioParams(BaseModel):
    name: str = "custom"
    title: str = "Custom scenario"
    description: str = ""
    available_litres: Optional[float] = Field(default=None, ge=0)
    water_factor: float = Field(default=1.0, ge=0, le=5)
    rainfall_mm: Optional[float] = Field(default=None, ge=0, le=300, description="Rain on days 1-2")
    rain_probability_pct: Optional[float] = Field(default=None, ge=0, le=100)
    temperature_delta_c: float = Field(default=0.0, ge=-10, le=15)
    efficiency_override: Optional[float] = Field(default=None, gt=0, le=1)
    irrigation_method: Optional[str] = None
    area_factor: float = Field(default=1.0, gt=0, le=10)
    priority_overrides: dict[str, float] = Field(default_factory=dict)
    delay_days: int = Field(default=0, ge=0, le=7)


PRESETS: dict[str, ScenarioParams] = {
    "normal": ScenarioParams(name="normal", title="Normal water availability", description="Current water and forecast, unchanged."),
    "severe_shortage": ScenarioParams(name="severe_shortage", title="Severe water shortage",
                                      description="Only 40% of the expected water is available.", water_factor=0.4),
    "unexpected_rain": ScenarioParams(name="unexpected_rain", title="Unexpected rainfall",
                                      description="25 mm rain with 90% probability over the next 2 days (hypothetical).",
                                      rainfall_mm=25, rain_probability_pct=90),
    "dry_spell": ScenarioParams(name="dry_spell", title="No rain arrives",
                                description="The forecast rain does not occur (0 mm, 0% on days 1-2).",
                                rainfall_mm=0, rain_probability_pct=0),
    "heatwave": ScenarioParams(name="heatwave", title="Heatwave",
                               description="Temperatures +6 C, raising reference ET by ~18% (hypothetical).", temperature_delta_c=6),
    "delayed_irrigation": ScenarioParams(name="delayed_irrigation", title="Irrigation delayed by 1 day",
                                         description="Irrigation is postponed one day; soil dries further.", delay_days=1),
    "increased_area": ScenarioParams(name="increased_area", title="Cultivated area +50%",
                                     description="Every field is 50% larger with the same water.", area_factor=1.5),
    "drip_irrigation": ScenarioParams(name="drip_irrigation", title="Switch to drip irrigation",
                                      description="All fields irrigated by drip (90% efficiency).", irrigation_method="drip"),
}


def apply_weather(weather: WeatherAssessment, p: ScenarioParams) -> WeatherAssessment:
    daily = [d.model_copy(deep=True) for d in weather.daily]
    for i, d in enumerate(daily):
        if p.temperature_delta_c:
            d.tmax_c += p.temperature_delta_c
            d.tmin_c += p.temperature_delta_c
            d.et0_mm = round(max(0.0, d.et0_mm * (1 + ET0_PER_DEG_C * p.temperature_delta_c)), 2)
        if i < 2:
            if p.rainfall_mm is not None:
                d.precip_mm = p.rainfall_mm
            if p.rain_probability_pct is not None:
                d.precip_prob_pct = p.rain_probability_pct
    notes = ["HYPOTHETICAL scenario weather"] if p != PRESETS["normal"] else []
    return assess(daily, weather.source, True if p.name != "normal" else weather.simulated, weather.scenario, notes)


def apply_context(ctx: FarmContext, p: ScenarioParams) -> FarmContext:
    c = ctx.model_copy(deep=True)
    for f in c.fields:
        f.area_ha = round(f.area_ha * p.area_factor, 4)
        if p.irrigation_method:
            f.irrigation_method = p.irrigation_method
            f.efficiency = float(ref.get_method(p.irrigation_method)["efficiency"])
        if p.efficiency_override:
            f.efficiency = p.efficiency_override
        f.delay_days = p.delay_days
    return c


def run_scenario(ctx: FarmContext, weather: WeatherAssessment, base_available: float, p: ScenarioParams, horizon: int = 3) -> ScenarioResult:
    c = apply_context(ctx, p)
    w = apply_weather(weather, p)
    avail = p.available_litres if p.available_litres is not None else base_available * p.water_factor
    r = run_core(c, w, avail, horizon, p.priority_overrides or None)
    total_area = sum(f.area_ha for f in c.fields) or 1.0
    rain_mm = sum(n.effective_rain_mm * n.area_ha for n in r.crop_water.fields) / total_area
    at_risk = [a.name for a in r.allocation.allocations if a.unmet_litres > 0.5]
    return ScenarioResult(
        name=p.name, title=p.title, description=p.description, hypothetical=p.name != "normal",
        total_demand_litres=r.allocation.total_demand_litres, total_allocated_litres=r.allocation.total_allocated_litres,
        deficit_litres=r.allocation.deficit_litres, rainfall_contribution_mm=round(rain_mm, 1),
        available_litres=r.allocation.available_litres, at_risk_fields=at_risk,
        actions={d.field_name: d.action for d in r.decision.decisions},
        field_allocations={a.name: a.allocated_litres for a in r.allocation.allocations},
    )


def compare(ctx: FarmContext, weather: WeatherAssessment, base_available: float, params: list[ScenarioParams], horizon: int = 3) -> ScenarioComparison:
    base = run_scenario(ctx, weather, base_available, PRESETS["normal"], horizon)
    results: list[ScenarioResult] = []
    changed: dict[str, dict[str, str]] = {}
    for p in params:
        res = run_scenario(ctx, weather, base_available, p, horizon)
        res.delta_vs_base = {
            "demand_litres": round(res.total_demand_litres - base.total_demand_litres, 1),
            "allocated_litres": round(res.total_allocated_litres - base.total_allocated_litres, 1),
            "deficit_litres": round(res.deficit_litres - base.deficit_litres, 1),
        }
        diffs = {f: f"{base.actions.get(f, Action.INSUFFICIENT_DATA).value} -> {a.value}" for f, a in res.actions.items() if base.actions.get(f) != a}
        if diffs:
            changed[p.name] = diffs
        results.append(res)
    return ScenarioComparison(base=base, scenarios=results, changed_actions=changed)
