"""Per-request state shared by the agents' tools, plus the Strands hook that records the execution trace."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from ..core.config import Settings
from ..core.logging import redact
from ..schemas.domain import (
    CropWaterAssessment, Farm, FarmContext, FarmerMessage, Field_, Language, OverallDecision, ScenarioComparison,
    TraceStep, WaterAllocationPlan, WeatherAssessment,
)
from .intent import ParsedQuery

SPECIALIST_TOOL_NAMES = {
    "farm_context_specialist": "Farm Context Agent",
    "weather_specialist": "Weather Intelligence Agent",
    "crop_water_specialist": "Crop Water Intelligence Agent",
    "water_budget_specialist": "Water Budget & Allocation Agent",
    "decision_specialist": "Irrigation Decision Agent",
    "scenario_specialist": "Scenario Simulation Agent",
    "communication_specialist": "Tamil Farmer Communication Agent",
}


@dataclass
class RunContext:
    settings: Settings
    farm: Farm
    fields: list[Field_]
    query: str
    parsed: ParsedQuery
    language: Language
    available_override_litres: Optional[float] = None
    priority_overrides: dict[str, float] = field(default_factory=dict)
    weather_scenario: Optional[str] = None
    weather_fetcher: Any = None  # callable(lat, lon, days) -> WeatherAssessment, injectable for tests

    ctx: Optional[FarmContext] = None
    weather: Optional[WeatherAssessment] = None
    crop_water: Optional[CropWaterAssessment] = None
    allocation: Optional[WaterAllocationPlan] = None
    decision: Optional[OverallDecision] = None
    scenarios: Optional[ScenarioComparison] = None
    message: Optional[FarmerMessage] = None
    answer: str = ""

    steps: list[TraceStep] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tool_calls: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)
    _starts: dict[str, float] = field(default_factory=dict)

    @property
    def available_litres(self) -> Optional[float]:
        if self.available_override_litres is not None:
            return self.available_override_litres
        return self.ctx.water_available_litres if self.ctx else self.farm.water_available_litres

    def add_step(self, step: TraceStep) -> None:
        with self.lock:
            step.seq = len(self.steps) + 1
            self.steps.append(step)

    def record(self, agent: str, tool: str | None, kind: str, status: str, summary: str, duration_ms: int = 0) -> None:
        started = datetime.now(timezone.utc) - timedelta(milliseconds=duration_ms)
        self.add_step(TraceStep(seq=0, agent=agent, tool=tool, kind=kind, status=status, summary=summary[:300],
                                duration_ms=duration_ms, started_at=started))


class TraceHook(HookProvider):
    """Records every real Strands tool invocation (name, status, duration, concise output) for one agent."""

    def __init__(self, rc: RunContext, agent_label: str, max_tool_calls: int):
        self.rc, self.agent_label, self.max_tool_calls = rc, agent_label, max_tool_calls

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self._before)
        registry.add_callback(AfterToolCallEvent, self._after)

    def _before(self, event: BeforeToolCallEvent) -> None:
        rc = self.rc
        with rc.lock:
            rc.tool_calls += 1
            over = rc.tool_calls > self.max_tool_calls
            rc._starts[event.tool_use["toolUseId"]] = time.perf_counter()
        if over:
            event.cancel_tool = f"Tool execution limit ({self.max_tool_calls}) reached for this request."

    def _after(self, event: AfterToolCallEvent) -> None:
        rc = self.rc
        started = rc._starts.pop(event.tool_use["toolUseId"], None)
        dur = int((time.perf_counter() - started) * 1000) if started else int((event.duration or 0) * 1000)
        name = event.tool_use["name"]
        status = event.result.get("status", "success")
        text = " ".join(c.get("text", "") for c in event.result.get("content", []) if isinstance(c, dict))
        summary = text
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "summary" in data:
                summary = str(data["summary"])
        except (ValueError, TypeError):
            pass
        is_specialist = name in SPECIALIST_TOOL_NAMES
        rc.record(
            agent=self.agent_label if not is_specialist else "Orchestrator",
            tool=name, kind="agent" if is_specialist else "tool",
            status="ok" if status == "success" else "error", summary=redact(summary), duration_ms=dur,
        )
        if status != "success":
            rc.errors.append(f"{name}: {redact(summary)[:200]}")
