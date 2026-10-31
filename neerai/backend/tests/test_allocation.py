import random

import pytest

from app.calculations.allocation import AllocationInput, allocate, priority_score


def inp(fid, demand, critical=False, stress=1.0, override=1.0, crop="groundnut", due=True):
    return AllocationInput(fid, fid, crop, demand, critical, stress, override, due)


def test_enough_water_meets_all_demand():
    p = allocate([inp("a", 100), inp("b", 200)], 1000)
    assert not p.scarcity_mode and p.deficit_litres == 0
    assert p.total_allocated_litres == 300


def test_never_exceeds_budget_and_reports_deficit():
    p = allocate([inp("a", 600, True), inp("b", 600)], 500)
    assert p.scarcity_mode
    assert p.total_allocated_litres <= 500
    assert p.deficit_litres == pytest.approx(p.total_demand_litres - p.total_allocated_litres, abs=0.1)


def test_critical_stage_funded_first():
    p = allocate([inp("calm", 400, critical=False, stress=0.2), inp("crit", 400, critical=True, stress=1.0)], 400)
    got = {a.field_id: a.allocated_litres for a in p.allocations}
    assert got["crit"] == 400 and got["calm"] == 0


def test_farmer_pin_overrides_priority():
    base = allocate([inp("a", 400, True), inp("b", 400, False)], 400)
    pinned = allocate([inp("a", 400, True, override=0.5), inp("b", 400, False, override=2.0)], 400)
    assert {a.field_id: a.allocated_litres for a in base.allocations}["a"] == 400
    assert {a.field_id: a.allocated_litres for a in pinned.allocations}["b"] == 400


def test_standard_tier_shares_by_score_and_caps_at_demand():
    p = allocate([inp("a", 100), inp("b", 1000)], 500)
    got = {a.field_id: a.allocated_litres for a in p.allocations}
    assert got["a"] <= 100 and sum(got.values()) <= 500 + 1e-6
    assert got["b"] > got["a"]


def test_not_due_fields_get_nothing():
    p = allocate([inp("a", 100, due=False), inp("b", 100)], 1000)
    assert {a.field_id: a.allocated_litres for a in p.allocations}["a"] == 0


def test_zero_water():
    p = allocate([inp("a", 100)], 0)
    assert p.total_allocated_litres == 0 and p.deficit_litres == 100


def test_negative_water_rejected():
    with pytest.raises(ValueError):
        allocate([inp("a", 1)], -1)


def test_priority_score_ranks_critical_and_stressed_higher():
    assert priority_score("paddy", True, 1.5, 1.0) > priority_score("paddy", False, 0.2, 1.0)


@pytest.mark.parametrize("seed", range(60))
def test_property_total_allocated_never_exceeds_available(seed):
    rnd = random.Random(seed)
    items = [inp(f"f{i}", rnd.uniform(0, 5e5), rnd.random() < 0.4, rnd.uniform(0, 3), rnd.choice([0.3, 1.0, 1.0, 2.0]),
                 rnd.choice(["paddy", "groundnut", "ragi", "banana"]), rnd.random() < 0.85) for i in range(rnd.randint(1, 7))]
    avail = rnd.uniform(0, 1.2e6)
    p = allocate(items, avail)
    assert p.total_allocated_litres <= avail + 1e-6
    for a in p.allocations:
        assert 0 <= a.allocated_litres <= a.demand_litres + 1e-6
        assert a.unmet_litres >= 0
