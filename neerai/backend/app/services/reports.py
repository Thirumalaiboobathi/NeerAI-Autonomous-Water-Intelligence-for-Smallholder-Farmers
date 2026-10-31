"""Markdown irrigation plan report (downloadable; optionally uploaded to S3 in AWS mode)."""
from __future__ import annotations

from ..agents.messages import action_label, fmt
from ..schemas.domain import Language, IrrigationPlanRecord


def plan_markdown(p: IrrigationPlanRecord, lang: Language = Language.en) -> str:
    d, a = p.decision, p.allocation
    lines = [
        f"# NeerAI Irrigation Plan - {p.label or p.id}",
        f"_Created: {p.created_at:%Y-%m-%d %H:%M} UTC. Weather: {p.weather_source}{' (SIMULATED)' if p.weather_simulated else ''}._",
        "",
        "> Decision support only. The farmer reviews and approves every action. NeerAI never controls pumps.",
        "",
        "## Water budget",
        f"- Available: **{fmt(a.available_litres)} L** ({a.available_litres / 1000:.1f} m3)",
        f"- Estimated demand now: **{fmt(a.total_demand_litres)} L**",
        f"- Allocated: **{fmt(a.total_allocated_litres)} L**; deficit: **{fmt(a.deficit_litres)} L**"
        f"{'  (WATER SCARCITY MODE)' if a.scarcity_mode else ''}",
        "",
        "## Field recommendations",
        "| Field | Action | Depth (mm) | Volume (L) | Timing | Confidence |",
        "|---|---|---|---|---|---|",
    ]
    for x in d.decisions:
        lines.append(f"| {x.field_name} | {action_label(x.action, Language.en)} | {x.recommended_depth_mm:.0f} | "
                     f"{fmt(x.recommended_volume_litres)} | {x.timing} | {x.confidence.value} |")
    lines += ["", "## Why this decision?"]
    for x in d.decisions:
        lines += [f"### {x.field_name}", *[f"- {r}" for r in x.reasoning], *[f"- Weather: {w}" for w in x.weather_considerations],
                  *[f"- Assumption: {s}" for s in x.assumptions], *[f"- Would change if: {c}" for c in x.would_change_if], ""]
    lines += ["## Validation", *[f"- {v}" for v in d.validation], "",
              "## Baseline for savings estimates",
              f"- Fixed-schedule baseline over the horizon: {fmt(p.baseline_litres)} L (modelled, not measured)."]
    return "\n".join(lines) + "\n"
