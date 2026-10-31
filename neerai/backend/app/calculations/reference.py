"""Configurable crop/soil/irrigation-method reference data (JSON, overridable via NEERAI_AGRONOMY_DIR)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_DEFAULT_DIR = Path(__file__).parent / "data"


def _dir() -> Path:
    return Path(os.environ.get("NEERAI_AGRONOMY_DIR", _DEFAULT_DIR))


@lru_cache
def _load(name: str) -> dict[str, Any]:
    return json.loads((_dir() / name).read_text(encoding="utf-8"))


def clear_cache() -> None:
    _load.cache_clear()


def crops() -> dict[str, dict[str, Any]]:
    return _load("crops.json")["crops"]


def soils() -> dict[str, dict[str, Any]]:
    return _load("soils.json")["soils"]


def methods() -> dict[str, dict[str, Any]]:
    return _load("soils.json")["methods"]


def get_crop(key: str) -> dict[str, Any]:
    try:
        return crops()[key]
    except KeyError:
        raise ValueError(f"unknown crop '{key}'. Supported: {', '.join(sorted(crops()))}") from None


def get_soil(key: str) -> dict[str, Any]:
    try:
        return soils()[key]
    except KeyError:
        raise ValueError(f"unknown soil '{key}'. Supported: {', '.join(sorted(soils()))}") from None


def get_method(key: str) -> dict[str, Any]:
    try:
        return methods()[key]
    except KeyError:
        raise ValueError(f"unknown irrigation method '{key}'. Supported: {', '.join(sorted(methods()))}") from None


DEFAULT_SOIL = "red_sandy_loam"
DEFAULT_METHOD = "flood"
DEFAULT_DAYS_SINCE_IRRIGATION = 3
