"""Deterministic query understanding: language, intent, stated water volume. Used to brief the orchestrator."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ..calculations import reference as ref
from ..calculations.units import to_litres
from ..schemas.domain import Language

_TAMIL = re.compile(r"[஀-௿]")
_VOLUME = re.compile(
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>m3|m³|cubic\s*met(?:re|er)s?|kl|litres?|liters?|ltrs?|l\b|லிட்டர்|கன\s*மீட்டர்)",
    re.IGNORECASE,
)
_DAYS = re.compile(r"(\d+|one|two|three)\s*day", re.IGNORECASE)
_WORD_NUM = {"one": 1, "two": 2, "three": 3}

PIPELINE = ["farm_context", "weather", "crop_water", "water_budget", "decision"]


@dataclass
class ParsedQuery:
    intent: str = "irrigation_assessment"
    language: Language = Language.en
    stated_water_litres: Optional[float] = None
    delay_days: int = 0
    focus_crop: Optional[str] = None
    steps: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)


def parse_volume_litres(text: str) -> Optional[float]:
    m = _VOLUME.search(text)
    if not m:
        return None
    num = float(m.group("num").replace(",", ""))
    unit = m.group("unit").lower().replace(" ", "")
    if unit in ("m3", "m³", "kl") or unit.startswith("cubic") or unit.startswith("கன"):
        return to_litres(num, "m3")
    return to_litres(num, "l")


def parse_query(query: str, default_language: Language = Language.en) -> ParsedQuery:
    q = query.lower()
    lang = default_language
    if _TAMIL.search(query) or "in tamil" in q or "tamil" in q and "explain" in q:
        lang = Language.ta
    if "in english" in q:
        lang = Language.en

    pq = ParsedQuery(language=lang)
    pq.stated_water_litres = parse_volume_litres(query)
    for crop_key in ref.crops():
        names = {crop_key, ref.get_crop(crop_key)["name_en"].split(" (")[0].lower(), ref.get_crop(crop_key)["name_ta"]}
        if any(n in q or n in query for n in names):
            pq.focus_crop = crop_key
            break
    if pq.focus_crop is None and ("rice" in q or "நெல்" in query):
        pq.focus_crop = "paddy"

    delay = ("delay" in q or "postpone" in q or "wait" in q or "தாமத" in query) and ("irrigat" in q or "நீர்ப்பாசன" in query or "day" in q)
    rain = "rain" in q or "மழை" in query
    scarcity = pq.stated_water_litres is not None or any(k in q for k in ("prioriti", "priority", "limited water", "only have", "shortage", "scarcity"))
    explain = "explain" in q or "விளக்க" in query

    if delay:
        pq.intent = "delay_scenario"
        m = _DAYS.search(query)
        pq.delay_days = int(_WORD_NUM.get(m.group(1).lower(), m.group(1))) if m else 1
        pq.scenarios = ["delayed_irrigation"]
    elif scarcity:
        pq.intent = "scarcity_allocation"
        pq.scenarios = []
    elif rain:
        pq.intent = "rain_impact"
        pq.scenarios = ["unexpected_rain", "dry_spell"]
    elif explain:
        pq.intent = "explain_plan"
    else:
        pq.intent = "irrigation_assessment"

    pq.steps = list(PIPELINE) + (["scenario"] if pq.scenarios else []) + ["communication"]
    return pq
