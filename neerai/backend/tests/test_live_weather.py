"""Live Open-Meteo validation. Skipped unless NEERAI_LIVE_TESTS=1 (needs internet; no key, no cost)."""
import os
from datetime import date

import httpx
import pytest

from app.integrations import weather as wx

pytestmark = pytest.mark.skipif(os.environ.get("NEERAI_LIVE_TESTS") != "1", reason="set NEERAI_LIVE_TESTS=1 to hit the live API")

MELUR = (10.0306, 78.3376)


def raw(days=3):
    r = httpx.get(wx.OpenMeteoProvider.url, params={
        "latitude": MELUR[0], "longitude": MELUR[1], "timezone": "auto", "forecast_days": days,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,et0_fao_evapotranspiration"}, timeout=10)
    r.raise_for_status()
    return r.json()


def test_api_units_are_what_the_parser_assumes():
    d = raw()["daily_units"]
    assert d["temperature_2m_max"] == "°C" and d["precipitation_sum"] == "mm"
    assert d["precipitation_probability_max"] == "%" and d["et0_fao_evapotranspiration"] == "mm"


def test_coordinates_snap_close_to_request_and_timezone_is_ist():
    j = raw()
    assert abs(j["latitude"] - MELUR[0]) < 0.2 and abs(j["longitude"] - MELUR[1]) < 0.2
    assert j["timezone"] == "Asia/Kolkata" and j["utc_offset_seconds"] == 19800


def test_provider_parses_horizon_ranges_and_dates():
    daily, meta = wx.OpenMeteoProvider().fetch(*MELUR, days=3)
    assert meta["simulated"] is False and len(daily) == 3
    assert abs((daily[0].date - date.today()).days) <= 1  # local-date vs UTC-date boundary
    assert [d.date for d in daily] == sorted(d.date for d in daily)
    for d in daily:
        assert 10 <= d.tmin_c <= d.tmax_c <= 50          # Tamil Nadu plausibility, degrees C
        assert 0 <= d.precip_mm < 500 and 0 <= d.precip_prob_pct <= 100
        assert 0 <= d.et0_mm < 15                          # mm/day


def test_assessment_is_labelled_live_and_fresh():
    w = wx.get_weather("openmeteo", *MELUR, days=3)
    assert w.simulated is False and "SIMULATED" not in w.source and "Open-Meteo" in w.source
    assert (wx.datetime.now(wx.timezone.utc) - w.fetched_at).total_seconds() < 30
    assert w.horizon_days == 3 and 0 <= w.rain_probability_48h_pct <= 100
    assert not any("SIMULATED" in n for n in w.notes)


def test_horizon_up_to_seven_days():
    daily, _ = wx.OpenMeteoProvider().fetch(*MELUR, days=7)
    assert len(daily) == 7
