"""Recommendations must change appropriately when rain, water, crop stage or efficiency change."""
from app.calculations.pipeline import build_context, run_core
from app.calculations.scenarios import ScenarioParams, apply_weather
from app.integrations.weather import get_weather
from app.schemas.domain import Action, Stage


def weather(name="dry"):
    return get_weather("mock", 10, 78, 3, name)


def acts(r):
    return {d.field_name.split(" ")[0]: d.action for d in r.decision.decisions}


def test_abundant_water_irrigates_due_fields_fully(madurai):
    farm, fields, ctx = madurai
    r = run_core(ctx, weather("dry"), 5e6)
    assert not r.allocation.scarcity_mode
    assert acts(r)["Paddy"] == Action.IRRIGATE_NOW
    assert r.decision.total_recommended_litres <= 5e6


def test_less_water_never_increases_allocation(madurai):
    _, _, ctx = madurai
    w = weather("dry")
    prev = None
    for avail in [2e6, 1e6, 6e5, 3e5, 1e5, 0]:
        r = run_core(ctx, w, avail)
        assert r.allocation.total_allocated_litres <= avail + 1e-6
        if prev is not None:
            assert r.allocation.total_allocated_litres <= prev + 1e-6
        prev = r.allocation.total_allocated_litres


def test_scarcity_mode_flags_deficit_and_prioritises(madurai):
    _, _, ctx = madurai
    r = run_core(ctx, weather("dry"), 4e5)
    assert r.allocation.scarcity_mode and r.allocation.deficit_litres > 0
    assert Action.PRIORITIZE_FIELD in {d.action for d in r.decision.decisions}


def test_heavy_rain_delays_paddy_and_cuts_demand(madurai):
    _, _, ctx = madurai
    dry = run_core(ctx, weather("dry"), 5e6)
    rain = run_core(ctx, weather("heavy_rain"), 5e6)
    assert rain.allocation.total_demand_litres < dry.allocation.total_demand_litres
    assert acts(rain)["Paddy"] == Action.DELAY_AND_MONITOR


def test_more_rain_monotonically_reduces_demand(madurai):
    _, _, ctx = madurai
    w = weather("dry")
    demands = []
    for mm in [0, 10, 25, 60]:
        wx = apply_weather(w, ScenarioParams(rainfall_mm=mm, rain_probability_pct=90))
        demands.append(run_core(ctx, wx, 5e6).allocation.total_demand_litres)
    assert demands == sorted(demands, reverse=True)
    assert demands[0] > demands[-1]


def test_heat_raises_demand(madurai):
    _, _, ctx = madurai
    base = run_core(ctx, weather("dry"), 5e6).allocation.total_demand_litres
    hot = run_core(ctx, weather("heatwave"), 5e6).allocation.total_demand_litres
    assert hot >= base


def test_stage_change_changes_priority(madurai):
    _, _, ctx = madurai
    c2 = ctx.model_copy(deep=True)
    for f in c2.fields:
        if f.crop == "groundnut":
            f.stage = Stage.initial
    r1, r2 = run_core(ctx, weather("dry"), 4e5), run_core(c2, weather("dry"), 4e5)
    g1 = next(a for a in r1.allocation.allocations if a.crop == "groundnut")
    g2 = next(a for a in r2.allocation.allocations if a.crop == "groundnut")
    assert g1.score > g2.score


def test_efficiency_change_changes_volume(madurai):
    _, _, ctx = madurai
    c2 = ctx.model_copy(deep=True)
    for f in c2.fields:
        f.efficiency = 0.9
    a = run_core(ctx, weather("dry"), 5e6).allocation.total_demand_litres
    b = run_core(c2, weather("dry"), 5e6).allocation.total_demand_litres
    assert b < a


def test_farmer_priority_override_changes_allocation(madurai):
    _, fields, ctx = madurai
    paddy = next(f for f in fields if f.crop == "paddy")
    base = run_core(ctx, weather("dry"), 4e5)
    pinned = run_core(ctx, weather("dry"), 4e5, overrides={paddy.id: 3.0})

    def got(r):
        return next(a.allocated_litres for a in r.allocation.allocations if a.crop == "paddy")

    assert got(pinned) > got(base)


def test_decisions_carry_explainability(madurai):
    _, _, ctx = madurai
    for d in run_core(ctx, weather("uncertain_rain"), 7e5).decision.decisions:
        assert d.reasoning and d.assumptions and d.would_change_if and d.weather_considerations
        assert d.confidence.value in ("low", "medium", "high")


def test_simulated_weather_lowers_confidence(madurai):
    _, _, ctx = madurai
    r = run_core(ctx, weather("dry"), 5e6)
    assert all(d.confidence.value != "high" for d in r.decision.decisions)
    assert any("SIMULATED" in d.weather_considerations[0] for d in r.decision.decisions)


def test_validation_passes_and_never_exceeds_budget(madurai):
    _, _, ctx = madurai
    r = run_core(ctx, weather("uncertain_rain"), 3e5)
    assert r.decision.validation[0].startswith("PASS")
    assert r.decision.total_recommended_litres <= 3e5
    assert r.decision.requires_farmer_approval


def test_missing_water_volume_is_blocking(madurai):
    farm, fields, _ = madurai
    farm.water_available_litres = None
    ctx = build_context(farm, fields)
    assert ctx.blocking_missing


def test_unknown_crop_reported_not_crashing(madurai):
    farm, fields, _ = madurai
    fields[0].crop = "dragonfruit"
    ctx = build_context(farm, fields)
    assert any("dragonfruit" in b for b in ctx.blocking_missing)
