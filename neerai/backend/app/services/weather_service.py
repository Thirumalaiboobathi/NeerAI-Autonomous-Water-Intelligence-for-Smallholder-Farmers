"""Weather lookup with a short TTL cache (live providers only; mock data is cheap and deterministic)."""
from __future__ import annotations

import threading
import time
from datetime import date

from ..core.config import Settings
from ..integrations import weather as wx
from ..schemas.domain import WeatherAssessment


class WeatherService:
    TTL_S = 600

    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[tuple, tuple[float, WeatherAssessment]] = {}
        self._lock = threading.Lock()

    def get(self, lat: float, lon: float, scenario: str | None = None, days: int | None = None) -> WeatherAssessment:
        s = self.settings
        days = days or s.planning_horizon_days
        scenario = scenario or s.weather_scenario
        key = (round(lat, 2), round(lon, 2), s.weather_provider, scenario, days, date.today())
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < self.TTL_S:
                return hit[1].model_copy(deep=True)
        w = wx.get_weather(s.weather_provider, lat, lon, days, scenario, s.weather_timeout_s)
        with self._lock:
            self._cache[key] = (time.time(), w)
        return w.model_copy(deep=True)
