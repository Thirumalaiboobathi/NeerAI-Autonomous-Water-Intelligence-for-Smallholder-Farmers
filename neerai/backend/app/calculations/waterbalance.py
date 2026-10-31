"""Crop water demand via the FAO-56 single-coefficient approach and a simple root-zone depletion balance.

ETc = Kc x ET0.  Total available water TAW = 1000 (FC - WP) Zr; readily available RAW = p TAW.
Irrigation is triggered when projected depletion Dr reaches RAW (earlier for critical stages).
Paddy is modelled as a ponded system: the buffer is standing water, losses are ETc + percolation.

Simplifications (documented, surfaced to the user as assumptions):
- Effective rainfall per day = 0.8 x (P - 2 mm) for P > 2 mm, weighted by forecast probability (risk-adjusted).
- Rain beyond current depletion is treated as drainage/runoff (no carry-over storage).
- Soil moisture readings, when given, replace the estimated starting depletion.
"""
from __future__ import annotations

from typing import Optional

from ..schemas.domain import DailyWeather, FieldContext, FieldWaterNeed, Stage
from . import reference as ref
from .units import depth_to_litres

CRITICAL_TRIGGER_FACTOR = 0.8  # critical stages trigger irrigation at 80% of RAW
RAIN_SKIP_MM = 2.0
RAIN_EFFICIENCY = 0.8
RAIN_MIN_PROB = 0.30  # forecasts below 30% chance are not credited


def effective_rain(precip_mm: float) -> float:
    """Daily effective rainfall (mm): 80% of rain above 2 mm; small showers are ignored."""
    return max(0.0, precip_mm - RAIN_SKIP_MM) * RAIN_EFFICIENCY


def crop_coefficient(crop: str, stage: Stage | str) -> float:
    return float(ref.get_crop(crop)["kc"][Stage(stage).value])


def etc(kc: float, et0_mm: float) -> float:
    """FAO-56: ETc = Kc x ET0."""
    return kc * et0_mm


def taw_raw(crop: str, stage: Stage | str, soil: str) -> tuple[float, float]:
    """Return (TAW, RAW) in mm for the root zone (or ponded buffer for paddy)."""
    c = ref.get_crop(crop)
    if c.get("ponded"):
        return float(c["ponded_buffer_mm"]), float(c["ponded_buffer_mm"]) - float(c["ponded_trigger_mm"])
    s = ref.get_soil(soil)
    zr = float(c["root_depth_m"][Stage(stage).value])
    taw = 1000.0 * (s["fc"] - s["wp"]) * zr
    return taw, float(c["p"]) * taw


def initial_depletion(
    ctx: FieldContext, taw: float, raw: float, etc_day: float, percolation: float
) -> tuple[float, str]:
    """Starting root-zone depletion (mm) and where it came from. `ctx.delay_days` adds hypothetical extra dry days."""
    c = ref.get_crop(ctx.crop)
    loss = etc_day + (percolation if c.get("ponded") else 0.0)
    if ctx.soil_moisture_pct is not None and not c.get("ponded"):
        s = ref.get_soil(ctx.soil_type)
        theta = ctx.soil_moisture_pct / 100.0
        zr = float(c["root_depth_m"][ctx.stage.value])
        dr = max(0.0, min(taw, 1000.0 * (s["fc"] - theta) * zr))
        src = "measured soil moisture reading"
    else:
        days = ctx.days_since_irrigation
        src = "estimated from days since last irrigation"
        if days is None:
            days = ref.DEFAULT_DAYS_SINCE_IRRIGATION
            src = f"assumed {days} days since last irrigation (not provided)"
        dr = max(0.0, min(taw, days * loss))
    if ctx.delay_days:
        dr = min(taw, dr + ctx.delay_days * loss)
        src += f" + {ctx.delay_days} day(s) of hypothetical delay"
    return dr, src


def field_water_need(
    ctx: FieldContext,
    daily: list[DailyWeather],
    horizon_days: int,
    *,
    irrigation_due_horizon_days: int = 1,
    rain_defer_prob_pct: float = 60.0,
) -> FieldWaterNeed:
    crop = ref.get_crop(ctx.crop)
    soil = ref.get_soil(ctx.soil_type)
    days = daily[:horizon_days]
    if not days:
        raise ValueError("weather data is required to estimate crop water need")

    kc = crop_coefficient(ctx.crop, ctx.stage)
    et0_avg = sum(d.et0_mm for d in days) / len(days)
    etc_avg = etc(kc, et0_avg)
    taw, raw = taw_raw(ctx.crop, ctx.stage, ctx.soil_type)
    perc = float(soil["percolation_mm_day"]) if crop.get("ponded") else 0.0
    critical = ctx.stage.value in crop["critical_stages"]
    trigger = raw * (CRITICAL_TRIGGER_FACTOR if critical else 1.0)
    dr0, dr_src = initial_depletion(ctx, taw, raw, etc_avg, perc)

    def simulate(use_rain: bool) -> tuple[float, Optional[int], float, float]:
        """Return (depletion at horizon end, first day index crossing trigger, rain used, ETc total)."""
        dr, cross, rain_used, etc_total = dr0, (0 if dr0 >= trigger else None), 0.0, 0.0
        for i, d in enumerate(days):
            e = etc(kc, d.et0_mm) + perc
            etc_total += etc(kc, d.et0_mm)
            prob = d.precip_prob_pct / 100.0
            er = effective_rain(d.precip_mm) * prob if (use_rain and prob >= RAIN_MIN_PROB) else 0.0
            rain_used += min(er, dr + e)  # rain beyond what the root zone can absorb is lost
            dr = max(0.0, min(taw, dr + e - er))
            if cross is None and dr >= trigger:
                cross = i + 1
        return dr, cross, rain_used, etc_total

    end_no_rain, cross_no_rain, _, etc_total = simulate(False)
    end_rain, cross_rain, rain_used, _ = simulate(True)
    stress_now = dr0 >= trigger
    needs_dry = stress_now or cross_no_rain is not None
    net_no_rain = round(end_no_rain, 2) if needs_dry else 0.0
    rain_covers = needs_dry and end_rain < trigger  # forecast (probability-weighted) rain keeps the crop below stress
    net_rain = 0.0 if (not needs_dry or rain_covers) else round(end_rain, 2)

    eff = ctx.efficiency
    rain48 = days[:2]
    max_prob = max((d.precip_prob_pct for d in rain48), default=0.0)
    deep = dr0 >= 1.2 * raw if raw > 0 else False
    extra: list[str] = []
    defer = False
    if rain_covers and stress_now:
        if max_prob >= rain_defer_prob_pct and not (critical and deep):
            defer = True
        else:
            # rain is plausible but not reliable (or the crop cannot wait): hedge with half of the dry-weather need
            net_rain = round(0.5 * net_no_rain, 2)
            extra.append("Rain is uncertain or the crop cannot wait; applying half of the dry-weather requirement")
    days_to_stress = cross_rain if net_rain > 0 else None
    due = bool(net_rain > 0 and (stress_now or (days_to_stress is not None and days_to_stress <= irrigation_due_horizon_days)))
    gross = net_rain / eff if eff > 0 else net_rain
    volume = depth_to_litres(ctx.area_ha, gross)

    # Baseline: fixed-schedule irrigation ignoring weather (documented in impact metrics).
    baseline_depth = float(crop["baseline_depth_mm"])
    baseline_events = max(1, round(horizon_days / float(crop["baseline_interval_days"])))
    baseline_vol = depth_to_litres(ctx.area_ha, baseline_depth * baseline_events / eff if eff > 0 else baseline_depth)

    assumptions = list(ctx.assumed) + extra
    assumptions.append(f"Initial depletion {dr_src}")
    assumptions.append("Effective rain = 0.8 x (rain - 2 mm), weighted by forecast probability")
    if crop.get("ponded"):
        assumptions.append(f"Paddy modelled as ponded: ETc + {perc:g} mm/day percolation; buffer {taw:g} mm")

    return FieldWaterNeed(
        field_id=ctx.field_id, name=ctx.name, crop=ctx.crop, stage=ctx.stage, area_ha=ctx.area_ha,
        kc=round(kc, 3), et0_mm_day=round(et0_avg, 2), etc_mm_day=round(etc_avg, 2),
        taw_mm=round(taw, 1), raw_mm=round(raw, 1), depletion_mm=round(dr0, 1), depletion_source=dr_src,
        horizon_days=len(days), etc_horizon_mm=round(etc_total, 1), effective_rain_mm=round(rain_used, 1),
        net_without_rain_mm=net_no_rain, net_requirement_mm=net_rain, gross_requirement_mm=round(gross, 1),
        volume_litres=round(volume, 0), efficiency=eff, stress_now=stress_now, days_to_stress=days_to_stress,
        due=due, defer_for_rain=defer, rain_covers=rain_covers, critical_stage=critical,
        stress_ratio=round(dr0 / raw, 2) if raw > 0 else 0.0,
        baseline_volume_litres=round(baseline_vol, 0), assumptions=assumptions,
    )
