"""Domain entities and structured agent outputs (Pydantic). Every important agent output has a schema here."""
from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:10]}"


class Language(str, Enum):
    en = "en"
    ta = "ta"


class Stage(str, Enum):
    initial = "initial"
    development = "development"
    mid = "mid"
    late = "late"


class Action(str, Enum):
    IRRIGATE_NOW = "IRRIGATE_NOW"
    DELAY_AND_MONITOR = "DELAY_AND_MONITOR"
    PARTIAL_IRRIGATION = "PARTIAL_IRRIGATION"
    PRIORITIZE_FIELD = "PRIORITIZE_FIELD"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class Confidence(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


# ───────────────────────── Entities ─────────────────────────

class Farmer(BaseModel):
    id: str = Field(default_factory=lambda: new_id("farmer"))
    name: str = "Farmer"
    preferred_language: Language = Language.ta


class FarmCreate(BaseModel):
    farmer_name: str = Field(default="Farmer", max_length=80)
    farm_name: str = Field(default="My farm", max_length=80)
    village: str = Field(default="", max_length=80)
    district: str = Field(default="Madurai", max_length=80)
    latitude: float = Field(default=9.9252, ge=-90, le=90)
    longitude: float = Field(default=78.1198, ge=-180, le=180)
    water_source: str = Field(default="borewell", max_length=40)
    water_available_litres: Optional[float] = Field(default=None, ge=0, le=1e10)
    water_is_estimate: bool = True
    is_demo: bool = False


class Farm(FarmCreate):
    id: str = Field(default_factory=lambda: new_id("farm"))
    created_at: datetime = Field(default_factory=now_utc)


class FieldCreate(BaseModel):
    farm_id: str
    name: str = Field(max_length=80)
    area: float = Field(gt=0, le=10_000)
    area_unit: Literal["ha", "acre"] = "ha"
    crop: str
    variety: Optional[str] = Field(default=None, max_length=60)
    sowing_date: Optional[date] = None
    stage: Stage = Stage.mid
    soil_type: Optional[str] = None
    irrigation_method: Optional[str] = None
    soil_moisture_pct: Optional[float] = Field(default=None, ge=0, le=60, description="Volumetric %, optional")
    days_since_irrigation: Optional[int] = Field(default=None, ge=0, le=60)
    priority_override: float = Field(default=1.0, ge=0.1, le=3.0)

    @field_validator("crop", "soil_type", "irrigation_method", mode="before")
    @classmethod
    def _norm(cls, v):
        return v.strip().lower() if isinstance(v, str) and v.strip() else (None if v == "" else v)


class Field_(BaseModel):
    """Persisted field (area normalised to hectares)."""
    id: str = Field(default_factory=lambda: new_id("field"))
    farm_id: str
    name: str
    area_ha: float
    crop: str
    variety: Optional[str] = None
    sowing_date: Optional[date] = None
    stage: Stage = Stage.mid
    soil_type: Optional[str] = None
    irrigation_method: Optional[str] = None
    soil_moisture_pct: Optional[float] = None
    days_since_irrigation: Optional[int] = None
    priority_override: float = 1.0
    created_at: datetime = Field(default_factory=now_utc)


# ───────────────────────── Agent outputs ─────────────────────────

class FieldContext(BaseModel):
    field_id: str
    name: str
    crop: str
    crop_name_en: str
    crop_name_ta: str
    stage: Stage
    area_ha: float
    soil_type: str
    irrigation_method: str
    efficiency: float
    soil_moisture_pct: Optional[float] = None
    days_since_irrigation: Optional[int] = None
    priority_override: float = 1.0
    delay_days: int = Field(default=0, description="Hypothetical extra days without irrigation (scenarios)")
    assumed: list[str] = Field(default_factory=list, description="Inputs that were defaulted")


class FarmContext(BaseModel):
    """Output of the Farm Context Agent."""
    farm_id: str
    farmer_name: str
    village: str
    district: str
    latitude: float
    longitude: float
    water_source: str
    water_available_litres: Optional[float]
    water_is_estimate: bool
    fields: list[FieldContext]
    missing_inputs: list[str] = Field(default_factory=list)
    blocking_missing: list[str] = Field(default_factory=list)
    is_demo: bool = False

    @property
    def total_area_ha(self) -> float:
        return round(sum(f.area_ha for f in self.fields), 4)


class DailyWeather(BaseModel):
    date: date
    tmax_c: float
    tmin_c: float
    precip_mm: float
    precip_prob_pct: float
    et0_mm: float


class WeatherAssessment(BaseModel):
    """Output of the Weather Intelligence Agent."""
    horizon_days: int
    daily: list[DailyWeather]
    rain_probability_48h_pct: float
    expected_rain_48h_mm: float
    expected_rain_horizon_mm: float
    avg_et0_mm_day: float
    max_temp_c: float
    heat_risk: Literal["none", "moderate", "high"]
    forecast_confidence: Confidence
    source: str
    simulated: bool
    fetched_at: datetime = Field(default_factory=now_utc)
    scenario: Optional[str] = None
    notes: list[str] = Field(default_factory=list)


class FieldWaterNeed(BaseModel):
    field_id: str
    name: str
    crop: str
    stage: Stage
    area_ha: float
    kc: float
    et0_mm_day: float
    etc_mm_day: float
    taw_mm: float
    raw_mm: float
    depletion_mm: float
    depletion_source: str
    horizon_days: int
    etc_horizon_mm: float
    effective_rain_mm: float
    net_without_rain_mm: float
    net_requirement_mm: float
    gross_requirement_mm: float
    volume_litres: float
    efficiency: float
    stress_now: bool
    days_to_stress: Optional[int]
    due: bool
    defer_for_rain: bool
    rain_covers: bool = False
    critical_stage: bool
    stress_ratio: float
    baseline_volume_litres: float
    assumptions: list[str] = Field(default_factory=list)


class CropWaterAssessment(BaseModel):
    """Output of the Crop Water Intelligence Agent."""
    fields: list[FieldWaterNeed]
    total_demand_litres: float
    total_due_demand_litres: float
    method: str = "FAO-56 single crop coefficient: ETc = Kc x ET0, root-zone depletion balance"
    is_estimate: bool = True


class FieldAllocation(BaseModel):
    field_id: str
    name: str
    crop: str
    demand_litres: float
    allocated_litres: float
    unmet_litres: float
    fraction_met: float
    rank: int
    score: float
    tier: Literal["critical", "standard", "deferred"]
    rationale: list[str]


class WaterAllocationPlan(BaseModel):
    """Output of the Water Budget and Allocation Agent."""
    available_litres: float
    total_demand_litres: float
    total_allocated_litres: float
    deficit_litres: float
    scarcity_mode: bool
    allocations: list[FieldAllocation]
    method: str = "Priority tiers (critical first) then score-weighted water-filling, capped at demand"
    notes: list[str] = Field(default_factory=list)


class IrrigationDecision(BaseModel):
    field_id: str
    field_name: str
    crop: str
    action: Action
    reasoning: list[str]
    recommended_depth_mm: float
    recommended_volume_litres: float
    timing: str
    weather_considerations: list[str]
    crop_stage_considerations: list[str]
    confidence: Confidence
    assumptions: list[str]
    would_change_if: list[str]


class OverallDecision(BaseModel):
    """Output of the Irrigation Decision Agent."""
    headline_action: Action
    summary: str
    total_recommended_litres: float
    available_litres: float
    scarcity_mode: bool
    decisions: list[IrrigationDecision]
    validation: list[str] = Field(default_factory=list)
    requires_farmer_approval: bool = True


class ScenarioResult(BaseModel):
    name: str
    title: str
    description: str
    hypothetical: bool = True
    total_demand_litres: float
    total_allocated_litres: float
    deficit_litres: float
    rainfall_contribution_mm: float
    available_litres: float
    at_risk_fields: list[str]
    actions: dict[str, Action]
    field_allocations: dict[str, float] = Field(default_factory=dict)
    delta_vs_base: dict[str, float] = Field(default_factory=dict)


class ScenarioComparison(BaseModel):
    """Output of the Scenario Simulation Agent."""
    base: ScenarioResult
    scenarios: list[ScenarioResult]
    changed_actions: dict[str, dict[str, str]] = Field(default_factory=dict)
    disclaimer: str = "Scenario weather and water values are hypothetical inputs, not forecasts."


class FarmerMessage(BaseModel):
    """Output of the Tamil Farmer Communication Agent."""
    language: Language
    headline: str
    steps: list[str]
    short_summary: str
    voice_text: str
    verified_numbers: bool = True


class TraceStep(BaseModel):
    seq: int
    agent: str
    tool: Optional[str] = None
    kind: Literal["agent", "tool", "fallback", "validation"] = "tool"
    status: Literal["ok", "error", "fallback"] = "ok"
    started_at: datetime = Field(default_factory=now_utc)
    duration_ms: int = 0
    summary: str = ""


class AgentExecution(BaseModel):
    id: str = Field(default_factory=lambda: new_id("exec"))
    farm_id: Optional[str] = None
    query: str
    language: Language = Language.en
    intent: str = "irrigation_assessment"
    mode: str = "demo"
    status: Literal["completed", "partial", "failed"] = "completed"
    created_at: datetime = Field(default_factory=now_utc)
    duration_ms: int = 0
    steps: list[TraceStep] = Field(default_factory=list)
    context: Optional[FarmContext] = None
    weather: Optional[WeatherAssessment] = None
    crop_water: Optional[CropWaterAssessment] = None
    allocation: Optional[WaterAllocationPlan] = None
    decision: Optional[OverallDecision] = None
    scenarios: Optional[ScenarioComparison] = None
    message: Optional[FarmerMessage] = None
    answer: str = ""
    data_sources: list[str] = Field(default_factory=list)
    follow_up_questions: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class IrrigationPlanRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("plan"))
    farm_id: str
    execution_id: Optional[str] = None
    created_at: datetime = Field(default_factory=now_utc)
    label: str = ""
    available_litres: float
    total_demand_litres: float
    total_allocated_litres: float
    deficit_litres: float
    baseline_litres: float
    decision: OverallDecision
    allocation: WaterAllocationPlan
    weather_source: str
    weather_simulated: bool


class ScenarioRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("scn"))
    farm_id: str
    created_at: datetime = Field(default_factory=now_utc)
    comparison: ScenarioComparison
