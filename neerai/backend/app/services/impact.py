"""Impact metrics with an explicit baseline. We never present modelled numbers as measured savings."""
from __future__ import annotations

from pydantic import BaseModel

from ..repositories.base import EXECUTION, FARM, FIELD, SCENARIO, Store
from ..schemas.domain import AgentExecution, Field_, ScenarioRecord

BASELINE_DEFINITION = (
    "Baseline = fixed-schedule irrigation: each field receives its crop's usual application depth at the usual interval "
    "(sample values in crops.json), divided by application efficiency, regardless of weather or soil moisture, over the "
    "3-day planning horizon."
)


class SavingsBlock(BaseModel):
    label: str
    litres: float
    kind: str  # estimated_potential | simulated | measured
    note: str


class ImpactSummary(BaseModel):
    farms: int
    fields_supported: int
    decisions_generated: int
    scenarios_evaluated: int
    latest_total_demand_litres: float
    latest_total_allocation_litres: float
    latest_water_deficit_litres: float
    cumulative_demand_litres: float
    cumulative_allocated_litres: float
    cumulative_deficit_litres: float
    baseline_definition: str
    savings: list[SavingsBlock]
    additional_need_vs_baseline_litres: float
    by_farm: list[dict]


def summarize(store: Store) -> ImpactSummary:
    execs = [e for e in store.list(EXECUTION, AgentExecution, limit=1000) if e.decision and e.crop_water and e.allocation]
    # latest execution per farm (list is newest-first)
    latest: dict[str, AgentExecution] = {}
    for e in execs:
        if e.farm_id and e.farm_id not in latest:
            latest[e.farm_id] = e

    def baseline(e: AgentExecution) -> float:
        return sum(n.baseline_volume_litres for n in e.crop_water.fields)  # type: ignore[union-attr]

    def need(e: AgentExecution) -> float:
        return sum(n.volume_litres for n in e.crop_water.fields if n.due)  # type: ignore[union-attr]

    saved = extra = 0.0
    for e in latest.values():
        for n in e.crop_water.fields:  # type: ignore[union-attr]
            diff = n.baseline_volume_litres - (n.volume_litres if n.due else 0.0)
            if diff >= 0:
                saved += diff
            else:
                extra += -diff

    sim = 0.0
    n_scn = 0
    for rec in store.list(SCENARIO, ScenarioRecord, limit=1000):
        for r in rec.comparison.scenarios:
            n_scn += 1
            if r.delta_vs_base.get("demand_litres", 0) < 0:
                sim += -r.delta_vs_base["demand_litres"]
    for e in execs:
        if e.scenarios:
            n_scn += len(e.scenarios.scenarios)

    by_farm = [
        {"farm_id": fid, "demand_litres": e.allocation.total_demand_litres, "allocated_litres": e.allocation.total_allocated_litres,
         "deficit_litres": e.allocation.deficit_litres, "baseline_litres": round(baseline(e)), "need_litres": round(need(e))}
        for fid, e in latest.items() if e.allocation
    ]
    return ImpactSummary(
        farms=store.count(FARM), fields_supported=store.count(FIELD), decisions_generated=len(execs), scenarios_evaluated=n_scn,
        latest_total_demand_litres=round(sum(e.allocation.total_demand_litres for e in latest.values() if e.allocation)),
        latest_total_allocation_litres=round(sum(e.allocation.total_allocated_litres for e in latest.values() if e.allocation)),
        latest_water_deficit_litres=round(sum(e.allocation.deficit_litres for e in latest.values() if e.allocation)),
        cumulative_demand_litres=round(sum(e.allocation.total_demand_litres for e in execs if e.allocation)),
        cumulative_allocated_litres=round(sum(e.allocation.total_allocated_litres for e in execs if e.allocation)),
        cumulative_deficit_litres=round(sum(e.allocation.deficit_litres for e in execs if e.allocation)),
        baseline_definition=BASELINE_DEFINITION,
        savings=[
            SavingsBlock(label="Estimated potential savings vs baseline (latest plan per farm)", litres=round(saved),
                         kind="estimated_potential", note="Modelled from crop/soil/weather estimates; not measured."),
            SavingsBlock(label="Simulated savings across what-if scenarios", litres=round(sim), kind="simulated",
                         note="Hypothetical inputs (e.g. switching to drip); not a forecast."),
            SavingsBlock(label="Measured real-world savings", litres=0, kind="measured",
                         note="No farmer water-meter measurements recorded yet. NeerAI makes no measured-savings claim."),
        ],
        additional_need_vs_baseline_litres=round(extra),
        by_farm=by_farm,
    )
