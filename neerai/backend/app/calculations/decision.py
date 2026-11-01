"""Deterministic irrigation decision rules. The Irrigation Decision Agent calls these through a tool."""
from __future__ import annotations

from ..schemas.domain import (
    Action, Confidence, CropWaterAssessment, FarmContext, FieldAllocation, FieldWaterNeed, IrrigationDecision,
    OverallDecision, WaterAllocationPlan, WeatherAssessment,
)
from .units import litres_to_depth

ACTION_PRIORITY = {
    Action.PRIORITIZE_FIELD: 5, Action.IRRIGATE_NOW: 4, Action.PARTIAL_IRRIGATION: 3,
    Action.DELAY_AND_MONITOR: 2, Action.INSUFFICIENT_DATA: 1,
}


def _confidence(weather: WeatherAssessment, ctx_assumed: int, defer_or_rain_dependent: bool) -> Confidence:
    score = {"low": 0, "medium": 1, "high": 2}[weather.forecast_confidence.value]
    if ctx_assumed >= 2:
        score -= 1
    if weather.simulated:
        score -= 1
    if defer_or_rain_dependent and weather.forecast_confidence.value != "high":
        score -= 1
    return Confidence.high if score >= 2 else Confidence.medium if score >= 1 else Confidence.low


def decide_field(
    need: FieldWaterNeed, alloc: FieldAllocation | None, weather: WeatherAssessment, scarcity: bool,
    assumed_count: int, top_ranked: bool,
) -> IrrigationDecision:
    rain_txt = (
        f"Rain chance next 48h: {weather.rain_probability_48h_pct:.0f}%, expected {weather.expected_rain_48h_mm:.1f} mm "
        f"(forecast confidence {weather.forecast_confidence.value}; source: {weather.source}"
        f"{', SIMULATED' if weather.simulated else ''})."
    )
    stage_txt = (
        f"{need.crop} is in the {need.stage.value} stage"
        + (" - a water-critical stage." if need.critical_stage else " - not a peak-sensitivity stage.")
    )
    base_assump = [
        f"Kc {need.kc} x ET0 {need.et0_mm_day} mm/day = ETc {need.etc_mm_day} mm/day (FAO-56)",
        f"Root-zone depletion {need.depletion_mm} mm of readily-available {need.raw_mm} mm ({need.depletion_source})",
        f"Application efficiency {need.efficiency:.0%}",
    ] + need.assumptions[:3]
    reasoning: list[str] = []
    dr_ratio = f"{need.stress_ratio:.1f}x"

    def mk(action, depth, vol, timing, conf, reasons, change):
        return IrrigationDecision(
            field_id=need.field_id, field_name=need.name, crop=need.crop, action=action,
            reasoning=reasons, recommended_depth_mm=round(depth, 1), recommended_volume_litres=round(vol, 0),
            timing=timing, weather_considerations=[rain_txt], crop_stage_considerations=[stage_txt],
            confidence=conf, assumptions=base_assump, would_change_if=change,
        )

    # 1) rain-driven deferral
    if need.defer_for_rain:
        saved = need.net_without_rain_mm - need.net_requirement_mm
        reasoning = [
            f"Soil water is at {dr_ratio} of the stress threshold, but rain is likely within 48h.",
            f"Expected useful rain covers about {saved:.0f} mm of the {need.net_without_rain_mm:.0f} mm requirement.",
            "Delaying avoids irrigating water that rain would supply.",
        ]
        change = ["Rain does not arrive by tomorrow evening", "Soil moisture check shows the crop is wilting",
                  "Forecast rain probability drops below 50%"]
        return mk(Action.DELAY_AND_MONITOR, 0, 0, "Re-check tomorrow morning; irrigate if no rain by evening",
                  _confidence(weather, assumed_count, True), reasoning, change)

    # 2) nothing due now
    if not need.due:
        if need.rain_covers:
            reasoning = [f"Forecast rain (probability-weighted) is expected to keep the root zone below its stress threshold "
                         f"over the next {need.horizon_days} days (~{need.effective_rain_mm:.0f} mm useful rain)."]
            timing = "Do not irrigate now; re-check after the rain window"
        elif need.net_requirement_mm > 0 and need.days_to_stress:
            reasoning = [f"Crop is projected to reach its stress threshold in about {need.days_to_stress} day(s)."]
            timing = f"Plan irrigation of about {need.gross_requirement_mm:.0f} mm in {need.days_to_stress} day(s)"
        else:
            reasoning = [f"Root-zone water is adequate ({need.depletion_mm} mm depleted of {need.raw_mm} mm threshold)."]
            timing = "Check soil moisture again in 2 days"
        change = ["Heatwave raises ET0", "A soil moisture reading shows lower moisture than estimated"]
        return mk(Action.DELAY_AND_MONITOR, 0, 0, timing, _confidence(weather, assumed_count, False), reasoning, change)

    # 3) irrigation is due: depends on allocation
    demand = need.volume_litres
    got = alloc.allocated_litres if alloc else demand
    gross_depth = litres_to_depth(need.area_ha, got) if got > 0 else 0.0
    timing = "Irrigate today (early morning or evening to reduce evaporation)"
    change = ["Available water changes", "Rain arrives before irrigation", "Farmer raises or lowers this field's priority"]
    conf = _confidence(weather, assumed_count, False)
    if need.critical_stage:
        reasoning.append("Critical growth stage: water stress now would reduce yield most.")
    if need.stress_now:
        reasoning.append(f"Root zone has reached {dr_ratio} of its stress threshold.")
    else:
        reasoning.append("Root zone will reach its stress threshold within a day.")

    if got <= 0:
        reasoning.append("No water could be allocated: other higher-priority fields consume the budget.")
        return mk(Action.DELAY_AND_MONITOR, 0, 0, "Wait for more water; re-run the plan when supply changes",
                  Confidence.medium, reasoning, ["More water becomes available", "Priority changed by the farmer"])
    partial = bool(alloc and alloc.fraction_met < 0.99)
    if partial:
        reasoning.append(f"Water is limited: only {alloc.fraction_met:.0%} of the {need.gross_requirement_mm:.0f} mm need can be applied.")
    if scarcity and top_ranked:
        reasoning.append("Highest-priority field under water scarcity: irrigate this field first.")
        return mk(Action.PRIORITIZE_FIELD, gross_depth, got, timing, conf, reasoning, change)
    if partial:
        return mk(Action.PARTIAL_IRRIGATION, gross_depth, got, timing, conf, reasoning, change)
    reasoning.append(f"Apply about {need.gross_requirement_mm:.0f} mm ({got:,.0f} L) to refill the root zone.")
    return mk(Action.IRRIGATE_NOW, gross_depth, got, timing, conf, reasoning, change)


def decide_all(
    ctx: FarmContext, weather: WeatherAssessment, crop_water: CropWaterAssessment, plan: WaterAllocationPlan
) -> OverallDecision:
    by_alloc = {a.field_id: a for a in plan.allocations}
    ranked_due = [a for a in plan.allocations if a.rank > 0]
    top = ranked_due[0].field_id if ranked_due else None
    assumed = {f.field_id: len(f.assumed) for f in ctx.fields}
    decisions = [
        decide_field(n, by_alloc.get(n.field_id), weather, plan.scarcity_mode, assumed.get(n.field_id, 0), n.field_id == top)
        for n in crop_water.fields
    ]
    total = round(sum(d.recommended_volume_litres for d in decisions), 0)
    headline = max((d.action for d in decisions), key=lambda a: ACTION_PRIORITY[a]) if decisions else Action.INSUFFICIENT_DATA
    due_n = sum(1 for d in decisions if d.action in (Action.IRRIGATE_NOW, Action.PARTIAL_IRRIGATION, Action.PRIORITIZE_FIELD))
    if not decisions:
        summary = "Not enough information to recommend irrigation."
    elif due_n == 0:
        summary = "No irrigation needed right now; monitor soil moisture and the rain forecast."
    else:
        summary = f"Irrigate {due_n} field(s) with about {total:,.0f} L of {plan.available_litres:,.0f} L available."
        if plan.scarcity_mode:
            summary += f" Water scarcity mode: {plan.deficit_litres:,.0f} L of demand cannot be met."
    return OverallDecision(
        headline_action=headline, summary=summary, total_recommended_litres=total,
        available_litres=plan.available_litres, scarcity_mode=plan.scarcity_mode, decisions=decisions,
    )


def validate_decision(decision: OverallDecision, plan: WaterAllocationPlan) -> list[str]:
    """Cross-check invariants. Returns a list of human-readable findings (empty list never means 'unchecked')."""
    findings: list[str] = []
    ok = True
    if decision.total_recommended_litres > plan.available_litres + 1.0:
        ok = False
        findings.append("FAIL: recommended volume exceeds available water")
    if plan.total_allocated_litres > plan.available_litres + 1e-6:
        ok = False
        findings.append("FAIL: allocation exceeds water budget")
    for d in decision.decisions:
        if d.action == Action.DELAY_AND_MONITOR and d.recommended_volume_litres > 0:
            ok = False
            findings.append(f"FAIL: {d.field_name} delayed but has volume")
        if d.action in (Action.IRRIGATE_NOW, Action.PARTIAL_IRRIGATION, Action.PRIORITIZE_FIELD) and d.recommended_volume_litres <= 0:
            ok = False
            findings.append(f"FAIL: {d.field_name} irrigates with zero volume")
    if ok:
        findings.append("PASS: volumes within budget; actions consistent with volumes; farmer approval required")
    return findings
