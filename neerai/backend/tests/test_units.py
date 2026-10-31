import pytest
from app.calculations import units as u


def test_depth_to_litres_matches_spec():
    assert u.depth_to_litres(2.0, 30) == 600_000  # A x D x 10,000


def test_roundtrip_depth():
    assert u.litres_to_depth(1.5, u.depth_to_litres(1.5, 42.0)) == pytest.approx(42.0)


def test_acre_to_ha():
    assert u.area_to_ha(1, "acre") == pytest.approx(0.404686, abs=1e-5)
    assert u.area_to_ha(2.5, "ha") == 2.5


@pytest.mark.parametrize("bad", [0, -1])
def test_area_must_be_positive(bad):
    with pytest.raises(ValueError):
        u.area_to_ha(bad, "ha")


def test_unknown_unit():
    with pytest.raises(ValueError):
        u.area_to_ha(1, "bigha")
    with pytest.raises(ValueError):
        u.to_litres(1, "gallon")


def test_volume_conversion():
    assert u.to_litres(3, "m3") == 3000
    assert u.litres_to_m3(4500) == 4.5
    with pytest.raises(ValueError):
        u.to_litres(-1, "l")
