from datetime import date

import pytest

from app.calculations import reference as ref
from app.calculations.waterbalance import crop_coefficient, effective_rain, etc, field_water_need, taw_raw
from app.schemas.domain import DailyWeather, FieldContext, Stage


def day(i=0, p=0.0, prob=0, et0=5.0, tmax=34):
    return DailyWeather(date=date(2026, 1, 1 + i), tmax_c=tmax, tmin_c=24, precip_mm=p, precip_prob_pct=prob, et0_mm=et0)


def ctx(crop="groundnut", stage=Stage.mid, soil="red_sandy_loam", eff=0.6, area=1.0, moisture=None, days=None):
    c = ref.get_crop(crop)
    return FieldContext(field_id="f1", name="F", crop=crop, crop_name_en=c["name_en"], crop_name_ta=c["name_ta"], stage=stage,
                        area_ha=area, soil_type=soil, irrigation_method="furrow", efficiency=eff,
                        soil_moisture_pct=moisture, days_since_irrigation=days)


DRY = [day(i) for i in range(3)]


def test_etc_is_kc_times_et0():
    assert etc(1.15, 5.0) == pytest.approx(5.75)
    assert crop_coefficient("groundnut", "mid") == 1.15


def test_effective_rain_ignores_small_showers():
    assert effective_rain(1.5) == 0
    assert effective_rain(12) == pytest.approx(8.0)


def test_taw_raw_fao56_formula():
    taw, raw = taw_raw("groundnut", Stage.mid, "red_sandy_loam")
    assert taw == pytest.approx(1000 * (0.20 - 0.10) * 0.50)
    assert raw == pytest.approx(0.5 * taw)


def test_paddy_uses_ponded_buffer():
    taw, raw = taw_raw("paddy", Stage.mid, "clay_loam")
    assert (taw, raw) == (50, 20)


def test_measured_moisture_overrides_estimate():
    n = field_water_need(ctx(moisture=11.0), DRY, 3)
    assert "measured" in n.depletion_source
    assert n.depletion_mm == pytest.approx(1000 * (0.20 - 0.11) * 0.5, abs=0.1)


def test_default_days_is_declared_as_assumption():
    n = field_water_need(ctx(), DRY, 3)
    assert "assumed" in n.depletion_source


def test_volume_uses_area_and_efficiency():
    n = field_water_need(ctx(moisture=11.0, area=2.0), DRY, 3)
    assert n.volume_litres == pytest.approx(2.0 * n.gross_requirement_mm * 10_000, rel=0.01)
    assert n.gross_requirement_mm == pytest.approx(n.net_requirement_mm / 0.6, rel=0.01)


def test_rain_reduces_requirement():
    dry = field_water_need(ctx(moisture=11.0), DRY, 3)
    wet = field_water_need(ctx(moisture=11.0), [day(0, 25, 90), day(1, 25, 90), day(2)], 3)
    assert wet.net_requirement_mm < dry.net_requirement_mm
    assert wet.volume_litres < dry.volume_litres


def test_low_probability_rain_is_not_credited():
    a = field_water_need(ctx(moisture=11.0), DRY, 3)
    b = field_water_need(ctx(moisture=11.0), [day(0, 40, 10), day(1), day(2)], 3)
    assert a.net_requirement_mm == b.net_requirement_mm


def test_better_efficiency_needs_less_water():
    low = field_water_need(ctx(moisture=11.0, eff=0.5), DRY, 3)
    high = field_water_need(ctx(moisture=11.0, eff=0.9), DRY, 3)
    assert high.volume_litres < low.volume_litres


def test_higher_et0_raises_requirement():
    a = field_water_need(ctx(days=1), DRY, 3)
    b = field_water_need(ctx(days=1), [day(i, et0=8.0) for i in range(3)], 3)
    assert b.etc_horizon_mm > a.etc_horizon_mm


def test_stage_changes_demand():
    initial = field_water_need(ctx(stage=Stage.initial, days=3), DRY, 3)
    mid = field_water_need(ctx(stage=Stage.mid, days=3), DRY, 3)
    assert mid.etc_mm_day > initial.etc_mm_day
    assert mid.critical_stage and not initial.critical_stage


def test_wet_soil_not_due():
    n = field_water_need(ctx(moisture=19.5), DRY, 1)
    assert not n.due and n.volume_litres == 0


def test_rain_defers_stressed_noncritical_field():
    n = field_water_need(ctx(stage=Stage.late, moisture=14.0), [day(0, 30, 90), day(1, 30, 90), day(2)], 3)
    assert n.defer_for_rain and not n.due


def test_critical_deep_stress_does_not_wait_for_rain():
    n = field_water_need(ctx(stage=Stage.mid, moisture=10.5), [day(0, 12, 65), day(1, 12, 65), day(2)], 3)
    assert not n.defer_for_rain
