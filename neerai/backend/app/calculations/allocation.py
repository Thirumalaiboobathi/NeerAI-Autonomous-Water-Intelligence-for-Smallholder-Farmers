"""Transparent, deterministic water allocation. The LLM never performs this arithmetic.

Algorithm (documented in docs/ARCHITECTURE.md):
1. score_i = crop_weight x stage_factor(2.0 if critical else 1.0) x (1 + min(stress_ratio, 2)/2) x farmer_override
2. Fields are ranked by score.
3. Tier "critical": fields in a critical growth stage, deeply depleted (stress_ratio >= 1.2) or pinned by the
   farmer (override >= 1.5) are funded first, in rank order, up to their full demand. Fields the farmer
   de-prioritised (override <= 0.5) are never in this tier.
4. Tier "standard": the remaining water is shared by score-weighted water-filling, capped at each field's demand.
5. Invariant: sum(allocated) <= available, allocated_i <= demand_i.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..schemas.domain import FieldAllocation, FieldWaterNeed, WaterAllocationPlan
from . import reference as ref

EPS = 1e-6


@dataclass
class AllocationInput:
    field_id: str
    name: str
    crop: str
    demand_litres: float
    critical_stage: bool
    stress_ratio: float
    priority_override: float = 1.0
    due: bool = True


def priority_score(crop: str, critical_stage: bool, stress_ratio: float, override: float) -> float:
    weight = float(ref.get_crop(crop)["priority_weight"])
    stage_factor = 2.0 if critical_stage else 1.0
    urgency = 1.0 + min(max(stress_ratio, 0.0), 2.0) / 2.0
    return round(weight * stage_factor * urgency * override, 4)


def _waterfill(items: list[tuple[int, float, float]], budget: float) -> dict[int, float]:
    """items: (index, weight, cap). Returns allocation per index; weighted fair share capped by demand."""
    alloc = {i: 0.0 for i, _, _ in items}
    active = [(i, w, c) for i, w, c in items if c > EPS and w > 0]
    remaining = budget
    while active and remaining > EPS:
        total_w = sum(w for _, w, _ in active)
        capped = []
        for i, w, c in active:
            share = remaining * w / total_w
            if alloc[i] + share >= c - EPS:
                capped.append((i, c - alloc[i]))
        if not capped:
            for i, w, _ in active:
                alloc[i] += remaining * w / total_w
            remaining = 0.0
            break
        for i, add in capped:
            alloc[i] += add
            remaining -= add
        done = {i for i, _ in capped}
        active = [(i, w, c) for i, w, c in active if i not in done]
    return alloc


def allocate(inputs: list[AllocationInput], available_litres: float) -> WaterAllocationPlan:
    if available_litres < 0:
        raise ValueError("available water cannot be negative")
    due = [a for a in inputs if a.due and a.demand_litres > EPS]
    scored = {
        a.field_id: priority_score(a.crop, a.critical_stage, a.stress_ratio, a.priority_override) for a in due
    }
    ranked = sorted(due, key=lambda a: (-scored[a.field_id], a.field_id))
    total_demand = sum(a.demand_litres for a in due)
    remaining = float(available_litres)
    alloc: dict[str, float] = {a.field_id: 0.0 for a in inputs}
    tier: dict[str, str] = {a.field_id: "deferred" for a in inputs}
    notes: list[str] = []

    def is_critical(a: AllocationInput) -> bool:
        if a.priority_override <= 0.5:
            return False
        return a.critical_stage or a.stress_ratio >= 1.2 or a.priority_override >= 1.5

    scarcity = available_litres + EPS < total_demand
    if not scarcity:
        for a in due:
            alloc[a.field_id] = a.demand_litres
            tier[a.field_id] = "critical" if is_critical(a) else "standard"
        remaining -= total_demand
    else:
        for a in ranked:
            if is_critical(a):
                tier[a.field_id] = "critical"
                give = min(a.demand_litres, remaining)
                alloc[a.field_id] = give
                remaining -= give
        rest = [(idx, scored[a.field_id], a.demand_litres) for idx, a in enumerate(ranked) if not is_critical(a)]
        for a in ranked:
            if not is_critical(a):
                tier[a.field_id] = "standard"
        if rest and remaining > EPS:
            wf = _waterfill(rest, remaining)
            for idx, give in wf.items():
                alloc[ranked[idx].field_id] = give
                remaining -= give
        notes.append("Water scarcity mode: demand exceeds available water; critical-stage fields are funded first.")

    rank_of = {a.field_id: r + 1 for r, a in enumerate(ranked)}
    out: list[FieldAllocation] = []
    for a in inputs:
        got = min(math.floor(alloc[a.field_id] * 10) / 10, a.demand_litres if a.due else 0.0)
        demand = a.demand_litres if a.due else 0.0
        rationale: list[str] = []
        if not a.due:
            rationale.append("Not due for irrigation now (rain expected or soil water adequate); no water reserved.")
        else:
            if a.critical_stage:
                rationale.append("Crop is in a water-critical growth stage.")
            if a.stress_ratio >= 1.0:
                rationale.append(f"Root zone already at {a.stress_ratio:.1f}x the stress threshold.")
            if a.priority_override >= 1.5:
                rationale.append("Pinned as high priority by the farmer.")
            elif a.priority_override <= 0.5:
                rationale.append("De-prioritised by the farmer.")
            if scarcity and got + EPS < demand:
                rationale.append(f"Receives {100 * got / demand:.0f}% of its demand because water is limited.")
            elif got + EPS >= demand:
                rationale.append("Demand fully met.")
        out.append(FieldAllocation(
            field_id=a.field_id, name=a.name, crop=a.crop, demand_litres=round(demand, 1),
            allocated_litres=round(got, 1), unmet_litres=round(max(demand - got, 0.0), 1),
            fraction_met=round(got / demand, 3) if demand > EPS else 1.0,
            rank=rank_of.get(a.field_id, 0), score=scored.get(a.field_id, 0.0),
            tier=tier[a.field_id] if a.due else "deferred", rationale=rationale,
        ))
    out.sort(key=lambda f: (f.rank == 0, f.rank))
    total_alloc = round(sum(f.allocated_litres for f in out), 1)
    return WaterAllocationPlan(
        available_litres=round(available_litres, 1), total_demand_litres=round(total_demand, 1),
        total_allocated_litres=total_alloc, deficit_litres=round(max(total_demand - total_alloc, 0.0), 1),
        scarcity_mode=scarcity, allocations=out, notes=notes,
    )


def inputs_from_needs(needs: list[FieldWaterNeed], overrides: dict[str, float] | None = None) -> list[AllocationInput]:
    overrides = overrides or {}
    return [
        AllocationInput(
            field_id=n.field_id, name=n.name, crop=n.crop, demand_litres=n.volume_litres,
            critical_stage=n.critical_stage, stress_ratio=n.stress_ratio,
            priority_override=overrides.get(n.field_id, 1.0), due=n.due,
        )
        for n in needs
    ]
