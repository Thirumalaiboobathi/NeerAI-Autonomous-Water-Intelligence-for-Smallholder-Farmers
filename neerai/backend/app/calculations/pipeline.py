"""Pure, deterministic assessment pipeline: context -> crop water -> allocation -> decisions.

Used by the agent tools AND the scenario simulator, so a simulated 'normal' scenario always equals the live plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..schemas.domain import (
    CropWaterAssessment, Farm, FarmContext, Field_, FieldContext, OverallDecision, WaterAllocationPlan,
    WeatherAssessment,
)
from . import reference as ref
from .allocation import allocate, inputs_from_needs
from .decision import decide_all, validate_decision
from .waterbalance import field_water_need


def build_context(farm: Farm, fields: list[Field_]) -> FarmContext:
    """Normalise units and defaults; record every defaulted input as an explicit assumption."""
    out: list[FieldContext] = []
    missing: list[str] = []
    blocking: list[str] = []
    for f in fields:
        assumed: list[str] = []
        try:
            crop = ref.get_crop(f.crop)
        except ValueError as e:
            blocking.append(f"{f.name}: {e}")
            continue
        soil_key = f.soil_type or ref.DEFAULT_SOIL
        if not f.soil_type:
            assumed.append(f"Soil type not given; assumed {ref.get_soil(soil_key)['name_en']}")
            missing.append(f"{f.name}: soil type")
        elif f.soil_type not in ref.soils():
            blocking.append(f"{f.name}: unknown soil '{f.soil_type}'")
            continue
        method_key = f.irrigation_method or (ref.DEFAULT_METHOD)
        if not f.irrigation_method:
            assumed.append(f"Irrigation method not given; assumed {ref.get_method(method_key)['name_en']}")
            missing.append(f"{f.name}: irrigation method")
        elif f.irrigation_method not in ref.methods():
            blocking.append(f"{f.name}: unknown irrigation method '{f.irrigation_method}'")
            continue
        if f.soil_moisture_pct is None and f.days_since_irrigation is None:
            assumed.append("No soil-moisture reading or last-irrigation date; depletion is a rough estimate")
            missing.append(f"{f.name}: soil moisture reading (optional, improves accuracy)")
        if f.soil_moisture_pct is not None and not crop.get("ponded"):
            soil = ref.get_soil(soil_key)
            if f.soil_moisture_pct / 100 > soil["fc"] + 0.02:
                assumed.append(f"Soil moisture reading {f.soil_moisture_pct:g}% is above field capacity ({soil['fc'] * 100:g}%) for this soil; "
                               "treated as fully wet - please re-check the reading or soil type")
                missing.append(f"{f.name}: soil moisture reading looks inconsistent with soil type")
            elif f.soil_moisture_pct / 100 < soil["wp"] - 0.02:
                assumed.append(f"Soil moisture reading {f.soil_moisture_pct:g}% is below wilting point ({soil['wp'] * 100:g}%) for this soil; "
                               "treated as fully depleted - please re-check the reading or soil type")
                missing.append(f"{f.name}: soil moisture reading looks inconsistent with soil type")
        out.append(FieldContext(
            field_id=f.id, name=f.name, crop=f.crop, crop_name_en=crop["name_en"], crop_name_ta=crop["name_ta"],
            stage=f.stage, area_ha=f.area_ha, soil_type=soil_key, irrigation_method=method_key,
            efficiency=float(ref.get_method(method_key)["efficiency"]), soil_moisture_pct=f.soil_moisture_pct,
            days_since_irrigation=f.days_since_irrigation, priority_override=f.priority_override, assumed=assumed,
        ))
    if not out and not blocking:
        blocking.append("No fields registered for this farm")
    if farm.water_available_litres is None:
        missing.append("available water volume (required to allocate water)")
        blocking.append("Available water volume not provided")
    return FarmContext(
        farm_id=farm.id, farmer_name=farm.farmer_name, village=farm.village, district=farm.district,
        latitude=farm.latitude, longitude=farm.longitude, water_source=farm.water_source,
        water_available_litres=farm.water_available_litres, water_is_estimate=farm.water_is_estimate,
        fields=out, missing_inputs=missing, blocking_missing=blocking, is_demo=farm.is_demo,
    )


def compute_crop_water(ctx: FarmContext, weather: WeatherAssessment, horizon_days: int) -> CropWaterAssessment:
    needs = [field_water_need(f, weather.daily, horizon_days) for f in ctx.fields]
    return CropWaterAssessment(
        fields=needs,
        total_demand_litres=round(sum(n.volume_litres for n in needs), 0),
        total_due_demand_litres=round(sum(n.volume_litres for n in needs if n.due), 0),
    )


def compute_allocation(
    ctx: FarmContext, cw: CropWaterAssessment, available_litres: float, overrides: Optional[dict[str, float]] = None
) -> WaterAllocationPlan:
    merged = {f.field_id: f.priority_override for f in ctx.fields}
    merged.update(overrides or {})
    return allocate(inputs_from_needs(cw.fields, merged), available_litres)


@dataclass
class CoreResult:
    crop_water: CropWaterAssessment
    allocation: WaterAllocationPlan
    decision: OverallDecision


def run_core(
    ctx: FarmContext, weather: WeatherAssessment, available_litres: float, horizon_days: int = 3,
    overrides: Optional[dict[str, float]] = None,
) -> CoreResult:
    cw = compute_crop_water(ctx, weather, horizon_days)
    plan = compute_allocation(ctx, cw, available_litres, overrides)
    decision = decide_all(ctx, weather, cw, plan)
    decision.validation = validate_decision(decision, plan)
    return CoreResult(cw, plan, decision)
