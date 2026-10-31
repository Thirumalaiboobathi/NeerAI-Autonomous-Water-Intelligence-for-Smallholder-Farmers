"""Strands tools. Each specialist agent owns its deterministic tools; tools return compact JSON (with a `summary`)."""
from __future__ import annotations

import json

from strands import tool

from . import steps
from .runctx import RunContext


def _j(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, default=str)


def farm_context_tools(rc: RunContext) -> list:
    @tool
    def load_farm_context() -> str:
        """Load the farm, its fields, crop, soil, irrigation method and water source; normalise units to hectares and
        litres; list inputs that are missing or were defaulted."""
        return _j(steps.do_context(rc))

    @tool
    def set_available_water(volume: float, unit: str = "litres") -> str:
        """Use a water volume stated by the farmer instead of the stored estimate. unit must be 'litres' or 'm3'."""
        return _j(steps.do_set_water(rc, volume, unit))

    return [load_farm_context, set_available_water]


def weather_tools(rc: RunContext) -> list:
    @tool
    def fetch_weather_forecast(days: int = 3) -> str:
        """Fetch the weather forecast for the farm location (live provider, or clearly labelled simulated sample data)
        and assess rainfall probability, expected rain, temperature and forecast confidence."""
        return _j(steps.do_weather(rc, days))

    @tool
    def analyze_weather_risks() -> str:
        """Return heat-stress risk, forecast uncertainty notes and the daily forecast already fetched."""
        return _j(steps.do_weather_risks(rc))

    return [fetch_weather_forecast, analyze_weather_risks]


def crop_water_tools(rc: RunContext) -> list:
    @tool
    def compute_crop_water_requirements(horizon_days: int = 3) -> str:
        """Compute per-field crop water need with FAO-56 (ETc = Kc x ET0), root-zone depletion, effective rainfall and
        irrigation efficiency. Returns net/gross depth (mm) and volume (litres) per field."""
        return _j(steps.do_crop_water(rc, horizon_days))

    return [compute_crop_water_requirements]


def water_budget_tools(rc: RunContext) -> list:
    @tool
    def set_field_priority(field_name: str, multiplier: float) -> str:
        """Apply a farmer-defined priority multiplier (0.1 to 3.0) to a field, matched by name or crop."""
        return _j(steps.do_set_priority(rc, field_name, multiplier))

    @tool
    def allocate_water_budget() -> str:
        """Allocate the available irrigation water across fields with the deterministic priority algorithm. Never exceeds
        the water budget; reports deficit and unmet demand per field."""
        return _j(steps.do_allocate(rc))

    return [set_field_priority, allocate_water_budget]


def decision_tools(rc: RunContext) -> list:
    @tool
    def generate_irrigation_decision() -> str:
        """Combine weather, crop water and the allocation into a per-field irrigation decision (action, depth, volume,
        timing, confidence, assumptions, what would change the decision)."""
        return _j(steps.do_decide(rc))

    @tool
    def validate_irrigation_decision() -> str:
        """Check the decision against the water budget and internal consistency rules."""
        return _j(steps.do_validate(rc))

    return [generate_irrigation_decision, validate_irrigation_decision]


def scenario_tools(rc: RunContext) -> list:
    @tool
    def simulate_scenarios(scenario_names: list[str], delay_days: int = 1) -> str:
        """Run deterministic what-if scenarios. Names: normal, severe_shortage, unexpected_rain, dry_spell, heatwave,
        delayed_irrigation, increased_area, drip_irrigation. Results are hypothetical, not forecasts."""
        return _j(steps.do_scenarios(rc, scenario_names, delay_days))

    return [simulate_scenarios]


def communication_tools(rc: RunContext) -> list:
    @tool
    def compose_farmer_message(language: str = "en") -> str:
        """Create the farmer-facing message in simple Tamil ('ta') or English ('en') from the verified decision. Numbers,
        units and crop names are copied from tool results, never re-computed."""
        return _j(steps.do_message(rc, language))

    return [compose_farmer_message]
