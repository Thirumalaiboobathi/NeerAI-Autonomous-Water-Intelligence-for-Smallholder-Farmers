import pytest
from pydantic import ValidationError

from app.calculations import scenarios as sc
from app.integrations.weather import get_weather


@pytest.fixture()
def comp(madurai):
    _, _, ctx = madurai
    w = get_weather("mock", 10, 78, 3, "uncertain_rain")
    return sc.compare(ctx, w, 7e5, [sc.PRESETS[n] for n in sc.PRESETS if n != "normal"])


def by_name(comp):
    return {s.name: s for s in comp.scenarios}


def test_normal_scenario_equals_base(madurai):
    _, _, ctx = madurai
    w = get_weather("mock", 10, 78, 3, "uncertain_rain")
    c = sc.compare(ctx, w, 7e5, [sc.PRESETS["normal"]])
    assert c.scenarios[0].total_demand_litres == c.base.total_demand_litres
    assert c.changed_actions == {}


def test_severe_shortage_increases_deficit(comp):
    s = by_name(comp)["severe_shortage"]
    assert s.deficit_litres > comp.base.deficit_litres
    assert s.available_litres == pytest.approx(comp.base.available_litres * 0.4)


def test_unexpected_rain_reduces_demand(comp):
    assert by_name(comp)["unexpected_rain"].total_demand_litres < comp.base.total_demand_litres


def test_heatwave_does_not_reduce_demand(comp):
    assert by_name(comp)["heatwave"].total_demand_litres >= comp.base.total_demand_litres


def test_delay_does_not_reduce_demand(comp):
    assert by_name(comp)["delayed_irrigation"].total_demand_litres >= comp.base.total_demand_litres


def test_increased_area_raises_demand(comp):
    assert by_name(comp)["increased_area"].total_demand_litres > comp.base.total_demand_litres


def test_drip_reduces_demand(comp):
    assert by_name(comp)["drip_irrigation"].total_demand_litres < comp.base.total_demand_litres


def test_all_scenarios_respect_water_budget(comp):
    for s in comp.scenarios:
        assert s.total_allocated_litres <= s.available_litres + 1e-6
        assert s.hypothetical


def test_disclaimer_present(comp):
    assert "hypothetical" in comp.disclaimer.lower()


def test_param_validation():
    with pytest.raises(ValidationError):
        sc.ScenarioParams(rainfall_mm=-5)
    with pytest.raises(ValidationError):
        sc.ScenarioParams(efficiency_override=1.5)
