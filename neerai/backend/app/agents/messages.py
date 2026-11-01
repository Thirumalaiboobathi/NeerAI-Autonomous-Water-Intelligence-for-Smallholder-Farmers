"""Bilingual (Tamil / English) farmer messages built from verified numbers, plus a number-consistency guard.

Templates (not free generation) guarantee that numerals, units and crop names are preserved. In Bedrock mode the LLM
may write the final narrative, but `numbers_consistent` rejects it if it states quantities that no tool produced.
"""
from __future__ import annotations

import re
from typing import Optional

from ..schemas.domain import (
    Action, FarmerMessage, Language, OverallDecision, ScenarioComparison, WaterAllocationPlan,
    WeatherAssessment,
)
from ..calculations import reference as ref

ACTION_TEXT = {
    Language.en: {
        Action.IRRIGATE_NOW: "Irrigate now",
        Action.DELAY_AND_MONITOR: "Wait and monitor",
        Action.PARTIAL_IRRIGATION: "Irrigate partially",
        Action.PRIORITIZE_FIELD: "Irrigate this field first",
        Action.INSUFFICIENT_DATA: "More information needed",
    },
    Language.ta: {
        Action.IRRIGATE_NOW: "இப்போதே நீர்ப்பாசனம் செய்யவும்",
        Action.DELAY_AND_MONITOR: "காத்திருந்து கண்காணிக்கவும்",
        Action.PARTIAL_IRRIGATION: "பகுதி அளவு மட்டும் நீர் பாய்ச்சவும்",
        Action.PRIORITIZE_FIELD: "முதலில் இந்த வயலுக்கு நீர் பாய்ச்சவும்",
        Action.INSUFFICIENT_DATA: "மேலும் தகவல் தேவை",
    },
}


def fmt(n: float) -> str:
    return f"{round(n):,}"


def action_label(a: Action, lang: Language) -> str:
    return ACTION_TEXT[lang][a]


def _field_name(field_name: str, crop: str, lang: Language) -> str:
    """Use the crop's Tamil name when speaking Tamil so that voice output is clean."""
    if lang == Language.ta:
        try:
            return ref.get_crop(crop)["name_ta"] + " வயல்"
        except ValueError:
            return field_name
    try:
        return ref.get_crop(crop)["name_en"].split(" (")[0] + " field"
    except ValueError:
        return field_name


def compose(
    decision: OverallDecision, weather: WeatherAssessment, plan: Optional[WaterAllocationPlan], lang: Language,
    focus_crop: Optional[str] = None, scenarios: Optional[ScenarioComparison] = None,
) -> FarmerMessage:
    ds = sorted(decision.decisions, key=lambda d: (d.crop != focus_crop, -d.recommended_volume_litres))
    steps: list[str] = []
    ta = lang == Language.ta
    for d in ds:
        nm = _field_name(d.field_name, d.crop, lang)
        label = action_label(d.action, lang)
        if d.recommended_volume_litres > 0:
            steps.append(
                f"{nm}: {label} - {fmt(d.recommended_volume_litres)} லிட்டர் ({d.recommended_depth_mm:.0f} மிமீ)."
                if ta else f"{nm}: {label} - about {fmt(d.recommended_volume_litres)} L ({d.recommended_depth_mm:.0f} mm)."
            )
        else:
            steps.append(f"{nm}: {label}." )
    rain = weather.rain_probability_48h_pct
    if ta:
        head = (f"இன்றைய பரிந்துரை: மொத்தம் {fmt(decision.total_recommended_litres)} லிட்டர் நீர் "
                f"(கிடைக்கும் நீர் {fmt(decision.available_litres)} லிட்டர்).")
        if decision.scarcity_mode and plan:
            head = (f"தண்ணீர் பற்றாக்குறை: தேவை {fmt(plan.total_demand_litres)} லிட்டர், கிடைப்பது "
                    f"{fmt(plan.available_litres)} லிட்டர். முக்கிய நிலையில் உள்ள பயிருக்கு முதலில் நீர் வழங்கப்படுகிறது.")
        elif decision.total_recommended_litres == 0:
            head = "இன்று நீர்ப்பாசனம் தேவையில்லை; மண்ணின் ஈரப்பதத்தையும் மழை முன்னறிவிப்பையும் கவனிக்கவும்."
        steps.append(f"அடுத்த 48 மணி நேரத்தில் மழை பெய்யும் வாய்ப்பு {rain:.0f} சதவீதம்.")
        steps.append("மண்ணை விரலால் அழுத்தி ஈரப்பதத்தை சரிபார்த்து, மழை முன்னறிவிப்பை மீண்டும் பார்க்கவும்.")
        if weather.simulated:
            steps.append("குறிப்பு: இது மாதிரி (உருவகப்படுத்தப்பட்ட) வானிலை தரவு, நேரடி தரவு அல்ல.")
        steps.append("இது ஒரு பரிந்துரை மட்டுமே; இறுதி முடிவை நீங்களே எடுக்கவும்.")
    else:
        head = (f"Today's plan: about {fmt(decision.total_recommended_litres)} L of water "
                f"(available: {fmt(decision.available_litres)} L).")
        if decision.scarcity_mode and plan:
            head = (f"Water is short: demand {fmt(plan.total_demand_litres)} L, available {fmt(plan.available_litres)} L. "
                    "Fields in critical growth stages are watered first.")
        elif decision.total_recommended_litres == 0:
            head = "No irrigation is needed today; keep checking soil moisture and the rain forecast."
        steps.append(f"Chance of rain in the next 48 hours: {rain:.0f}%.")
        steps.append("Press the soil with your finger to check moisture, and look at the rain forecast again.")
        if weather.simulated:
            steps.append("Note: weather shown is SIMULATED sample data, not a live forecast.")
        steps.append("This is a recommendation only; you make the final decision.")
    if scenarios and scenarios.scenarios:
        s = scenarios.scenarios[0]
        steps.append(
            f"கற்பனை நிலையில் ({s.title}): தேவை {fmt(s.total_demand_litres)} லிட்டர், பற்றாக்குறை {fmt(s.deficit_litres)} லிட்டர்."
            if ta else f"If '{s.title}': demand {fmt(s.total_demand_litres)} L, shortfall {fmt(s.deficit_litres)} L."
        )
    short = head if len(steps) == 0 else head + " " + steps[0]
    voice = " ".join([head] + [re.sub(r"[()\-]", ",", s) for s in steps])
    return FarmerMessage(language=lang, headline=head, steps=steps, short_summary=short, voice_text=voice)


_QTY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(?:L\b|litres?|liters?|m3|m³|mm\b|%|ha\b|லிட்டர்|மிமீ|சதவீதம்)", re.IGNORECASE)


def states_quantity(text: str) -> bool:
    return bool(_QTY.search(text))


def numbers_consistent(text: str, allowed_numbers: set[float], rel_tol: float = 0.02) -> bool:
    """True if every quantity (number + unit) in `text` matches a number produced by deterministic tools."""
    for m in _QTY.finditer(text):
        val = float(m.group(1).replace(",", ""))
        if not any(abs(val - a) <= max(0.51, rel_tol * abs(a)) for a in allowed_numbers):
            return False
    return True


def collect_numbers(obj) -> set[float]:
    """Harvest every numeric value from a nested pydantic/JSON-like object, plus m3 and percent variants."""
    out: set[float] = set()

    def walk(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            out.add(float(x))
            out.add(round(float(x)))
            out.add(round(float(x) / 1000.0, 1))
            out.add(round(float(x) * 100.0))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple, set)):
            for v in x:
                walk(v)
        elif hasattr(x, "model_dump"):
            walk(x.model_dump(mode="json"))

    walk(obj)
    return out
