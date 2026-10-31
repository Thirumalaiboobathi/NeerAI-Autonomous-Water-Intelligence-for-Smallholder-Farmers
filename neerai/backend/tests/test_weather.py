import httpx
import pytest

from app.integrations import weather as wx


def test_mock_is_deterministic_and_labelled_simulated():
    a = wx.get_weather("mock", 10, 78, 3, "uncertain_rain")
    b = wx.get_weather("mock", 10, 78, 3, "uncertain_rain")
    assert a.daily == b.daily
    assert a.simulated and "SIMULATED" in a.source


def test_unknown_mock_scenario():
    with pytest.raises(ValueError):
        wx.MockWeatherProvider("monsoon-of-doom")


def test_heat_risk_levels():
    assert wx.get_weather("mock", 0, 0, 3, "heatwave").heat_risk == "high"
    assert wx.get_weather("mock", 0, 0, 3, "dry").heat_risk == "none"


def test_uncertain_rain_lowers_confidence():
    w = wx.get_weather("mock", 0, 0, 3, "uncertain_rain")
    assert w.forecast_confidence.value in ("low", "medium")
    assert any("uncertain" in n.lower() for n in w.notes)


def payload():
    return {"daily": {"time": ["2026-01-01", "2026-01-02", "2026-01-03"], "temperature_2m_max": [33, 34, 35],
                      "temperature_2m_min": [24, 24, 25], "precipitation_sum": [0.0, 5.0, None],
                      "precipitation_probability_max": [10, 70, None], "et0_fao_evapotranspiration": [4.5, 4.8, 5.0]}}


def client_with(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_open_meteo_parsing_marks_live_not_simulated():
    p = wx.OpenMeteoProvider(client=client_with(lambda r: httpx.Response(200, json=payload())))
    daily, meta = p.fetch(10, 78, 3)
    assert meta["simulated"] is False and len(daily) == 3
    assert daily[2].precip_mm == 0.0  # null handled, not invented
    assert wx.assess(daily, p.name, False).simulated is False


def test_open_meteo_rejects_incomplete_data():
    bad = payload()
    bad["daily"]["et0_fao_evapotranspiration"][1] = None
    p = wx.OpenMeteoProvider(client=client_with(lambda r: httpx.Response(200, json=bad)))
    with pytest.raises(ValueError):
        p.fetch(10, 78, 3)


def _boom(self, *a, **k):
    raise httpx.ConnectError("offline")


def test_auto_mode_falls_back_to_labelled_simulation(monkeypatch):
    monkeypatch.setattr(wx.OpenMeteoProvider, "fetch", _boom)
    w = wx.get_weather("auto", 10, 78, 3, "dry")
    assert w.simulated and any("Live weather unavailable" in n for n in w.notes)


def test_strict_live_mode_raises_instead_of_faking(monkeypatch):
    monkeypatch.setattr(wx.OpenMeteoProvider, "fetch", _boom)
    with pytest.raises(httpx.ConnectError):
        wx.get_weather("openmeteo", 10, 78, 3)
