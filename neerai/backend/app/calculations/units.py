"""Unit conversions. 1 mm of water over 1 ha = 10,000 litres."""
from __future__ import annotations

ACRE_TO_HA = 0.40468564224
LITRES_PER_MM_HA = 10_000.0


def area_to_ha(value: float, unit: str) -> float:
    unit = unit.lower()
    if value <= 0:
        raise ValueError("area must be positive")
    if unit in ("ha", "hectare", "hectares"):
        return round(value, 6)
    if unit in ("acre", "acres"):
        return round(value * ACRE_TO_HA, 6)
    raise ValueError(f"unsupported area unit: {unit}")


def ha_to_acre(ha: float) -> float:
    return ha / ACRE_TO_HA


def depth_to_litres(area_ha: float, depth_mm: float) -> float:
    """Water volume (L) = A (ha) x D (mm) x 10,000."""
    return area_ha * depth_mm * LITRES_PER_MM_HA


def litres_to_depth(area_ha: float, litres: float) -> float:
    if area_ha <= 0:
        raise ValueError("area must be positive")
    return litres / (area_ha * LITRES_PER_MM_HA)


def m3_to_litres(m3: float) -> float:
    return m3 * 1000.0


def litres_to_m3(litres: float) -> float:
    return litres / 1000.0


def to_litres(value: float, unit: str) -> float:
    unit = unit.lower()
    if value < 0:
        raise ValueError("volume cannot be negative")
    if unit in ("l", "litre", "litres", "liter", "liters"):
        return value
    if unit in ("m3", "cubic_metre", "cubic_metres", "kl"):
        return m3_to_litres(value)
    raise ValueError(f"unsupported volume unit: {unit}")
