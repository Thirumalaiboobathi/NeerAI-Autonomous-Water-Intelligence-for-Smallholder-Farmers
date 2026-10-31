"""Weather providers. Live data is never fabricated: any simulated series is flagged `simulated=True`."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Protocol

import httpx

from ..schemas.domain import Confidence, DailyWeather, WeatherAssessment

log = logging.getLogger("neerai.weather")

MOCK_SCENARIOS = {
    # (tmax, tmin, precip_mm, prob_pct, et0) per day for 5 days. Values are SAMPLE data for Madurai-like conditions.
    "uncertain_rain": [(34, 25, 0.0, 15, 5.2), (33, 25, 12.0, 60, 4.6), (33, 24, 6.0, 45, 4.4), (34, 25, 0.0, 20, 5.0), (35, 25, 0.0, 10, 5.4)],
    "dry": [(35, 25, 0.0, 5, 5.6), (36, 26, 0.0, 5, 5.8), (36, 26, 0.0, 5, 5.9), (35, 25, 0.0, 10, 5.6), (35, 25, 0.0, 10, 5.5)],
    "heatwave": [(40, 28, 0.0, 5, 7.2), (41, 28, 0.0, 5, 7.6), (42, 29, 0.0, 5, 7.9), (41, 28, 0.0, 10, 7.5), (40, 27, 0.0, 10, 7.2)],
    "heavy_rain": [(30, 24, 28.0, 90, 3.2), (29, 23, 35.0, 85, 3.0), (30, 24, 10.0, 60, 3.6), (31, 24, 2.0, 30, 4.2), (32, 25, 0.0, 15, 4.6)],
}


class WeatherProvider(Protocol):
    name: str

    def fetch(self, lat: float, lon: float, days: int) -> tuple[list[DailyWeather], dict]: ...


class MockWeatherProvider:
    name = "NeerAI deterministic sample weather (SIMULATED)"

    def __init__(self, scenario: str = "uncertain_rain", start: date | None = None):
        if scenario not in MOCK_SCENARIOS:
            raise ValueError(f"unknown mock weather scenario '{scenario}'. Options: {', '.join(MOCK_SCENARIOS)}")
        self.scenario = scenario
        self.start = start

    def fetch(self, lat: float, lon: float, days: int):
        start = self.start or date.today()
        rows = MOCK_SCENARIOS[self.scenario]
        daily = [
            DailyWeather(date=start + timedelta(days=i), tmax_c=r[0], tmin_c=r[1], precip_mm=r[2], precip_prob_pct=r[3], et0_mm=r[4])
            for i, r in enumerate(rows[: max(days, 1)])
        ]
        return daily, {"simulated": True, "scenario": self.scenario}


class OpenMeteoProvider:
    """Open-Meteo forecast API (free, no key). https://open-meteo.com/en/docs"""
    name = "Open-Meteo forecast API"
    url = "https://api.open-meteo.com/v1/forecast"

    def __init__(self, timeout: float = 6.0, client: httpx.Client | None = None):
        self.timeout = timeout
        self._client = client

    def fetch(self, lat: float, lon: float, days: int):
        params = {
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": max(min(days, 7), 1),
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,et0_fao_evapotranspiration",
        }
        c = self._client or httpx.Client(timeout=self.timeout)
        try:
            r = c.get(self.url, params=params)
            r.raise_for_status()
            d = r.json()["daily"]
        finally:
            if self._client is None:
                c.close()
        out = []
        for i, day in enumerate(d["time"]):
            if None in (d["temperature_2m_max"][i], d["temperature_2m_min"][i], d["et0_fao_evapotranspiration"][i]):
                raise ValueError("Open-Meteo returned incomplete data")
            out.append(DailyWeather(
                date=date.fromisoformat(day), tmax_c=d["temperature_2m_max"][i], tmin_c=d["temperature_2m_min"][i],
                precip_mm=d["precipitation_sum"][i] or 0.0,
                precip_prob_pct=(d.get("precipitation_probability_max") or [None] * len(d["time"]))[i] or 0.0,
                et0_mm=d["et0_fao_evapotranspiration"][i],
            ))
        return out, {"simulated": False}


def assess(daily: list[DailyWeather], source: str, simulated: bool, scenario: str | None = None, notes: list[str] | None = None) -> WeatherAssessment:
    if not daily:
        raise ValueError("no weather data")
    h48 = daily[:2]
    prob48 = max(d.precip_prob_pct for d in h48)
    exp48 = sum(d.precip_mm * d.precip_prob_pct / 100.0 for d in h48)
    tmax = max(d.tmax_c for d in daily[:3])
    heat = "high" if tmax >= 40 else "moderate" if tmax >= 37 else "none"
    mid = [d for d in h48 if 30 <= d.precip_prob_pct <= 70]
    conf = Confidence.low if len(mid) == len(h48) or (mid and simulated) else Confidence.medium if mid else Confidence.high
    n = list(notes or [])
    if mid:
        n.append("Rain probability is in the uncertain 30-70% range; treat rain benefit cautiously.")
    if heat != "none":
        n.append(f"Heat risk {heat}: max temperature {tmax:.0f} C raises crop water use.")
    if simulated:
        n.append("SIMULATED weather: not a live observation or forecast.")
    return WeatherAssessment(
        horizon_days=len(daily), daily=daily, rain_probability_48h_pct=prob48, expected_rain_48h_mm=round(exp48, 1),
        expected_rain_horizon_mm=round(sum(d.precip_mm * d.precip_prob_pct / 100.0 for d in daily), 1),
        avg_et0_mm_day=round(sum(d.et0_mm for d in daily) / len(daily), 2), max_temp_c=tmax, heat_risk=heat,
        forecast_confidence=conf, source=source, simulated=simulated, scenario=scenario, notes=n,
        fetched_at=datetime.now(timezone.utc),
    )


def get_weather(provider_name: str, lat: float, lon: float, days: int, scenario: str = "uncertain_rain", timeout: float = 6.0) -> WeatherAssessment:
    """Resolve a provider, with a clearly labelled simulated fallback when the live API fails (auto mode)."""
    if provider_name == "mock":
        p = MockWeatherProvider(scenario)
        daily, meta = p.fetch(lat, lon, days)
        return assess(daily, p.name, True, scenario)
    live = OpenMeteoProvider(timeout)
    try:
        daily, meta = live.fetch(lat, lon, days)
        return assess(daily, live.name, False)
    except Exception as exc:  # network, HTTP, schema
        log.warning("live weather failed: %s", type(exc).__name__)
        if provider_name == "openmeteo":
            raise
        p = MockWeatherProvider(scenario)
        daily, _ = p.fetch(lat, lon, days)
        return assess(daily, p.name, True, scenario,
                      notes=[f"Live weather unavailable ({type(exc).__name__}); using SIMULATED sample data instead."])
