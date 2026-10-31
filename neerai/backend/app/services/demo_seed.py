"""Load clearly-labelled sample farms from data/demo/sample_farms.json."""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from ..calculations.units import area_to_ha
from ..schemas.domain import Farm, FarmCreate, Field_, FieldCreate

_REPO_ROOT = Path(__file__).resolve().parents[3]


def demo_path() -> Path:
    return Path(os.environ.get("NEERAI_DEMO_DIR", _REPO_ROOT / "data" / "demo")) / "sample_farms.json"


def load_seed() -> dict:
    return json.loads(demo_path().read_text(encoding="utf-8"))


def field_from_create(fc: FieldCreate) -> Field_:
    return Field_(
        farm_id=fc.farm_id, name=fc.name, area_ha=area_to_ha(fc.area, fc.area_unit), crop=fc.crop, variety=fc.variety,
        sowing_date=fc.sowing_date, stage=fc.stage, soil_type=fc.soil_type, irrigation_method=fc.irrigation_method,
        soil_moisture_pct=fc.soil_moisture_pct, days_since_irrigation=fc.days_since_irrigation,
        priority_override=fc.priority_override,
    )


def build_demo(key: str = "madurai") -> tuple[Farm, list[Field_]]:
    seed = load_seed()
    entry = next((f for f in seed["farms"] if f["key"] == key), None)
    if entry is None:
        raise ValueError(f"unknown demo farm '{key}'")
    farm = Farm(**FarmCreate(**entry["farm"]).model_dump())
    fields: list[Field_] = []
    for raw in entry["fields"]:
        raw = dict(raw)
        off = raw.pop("sowing_date_offset_days", None)
        if off is not None:
            raw["sowing_date"] = date.today() + timedelta(days=off)
        fields.append(field_from_create(FieldCreate(farm_id=farm.id, **raw)))
    return farm, fields


def demo_keys() -> list[str]:
    return [f["key"] for f in load_seed()["farms"]]
