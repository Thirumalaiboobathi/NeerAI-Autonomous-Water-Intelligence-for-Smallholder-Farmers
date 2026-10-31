"""Request/response models for the REST API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..calculations.scenarios import ScenarioParams
from ..schemas.domain import (
    CropWaterAssessment, Farm, FarmContext, FarmerMessage, Field_, Language, OverallDecision, Stage, WaterAllocationPlan, WeatherAssessment,
)


class WaterInput(BaseModel):
    available_water: Optional[float] = Field(default=None, ge=0, le=1e10)
    available_water_unit: Literal["litres", "m3"] = "litres"


class AssessRequest(WaterInput):
    farm_id: str
    query: str = Field(default="Should I irrigate today?", min_length=1, max_length=500)
    language: Language = Language.en
    priority_overrides: dict[str, float] = Field(default_factory=dict)
    weather_scenario: Optional[str] = None


class ChatRequest(BaseModel):
    farm_id: str
    message: str = Field(min_length=1, max_length=500)
    language: Language = Language.en
    weather_scenario: Optional[str] = None


class PlanRequest(WaterInput):
    farm_id: str
    priority_overrides: dict[str, float] = Field(default_factory=dict)
    weather_scenario: Optional[str] = None
    save: bool = False
    label: str = Field(default="", max_length=80)


class PlanResult(BaseModel):
    plan_id: Optional[str] = None
    context: FarmContext
    weather: WeatherAssessment
    crop_water: CropWaterAssessment
    allocation: WaterAllocationPlan
    decision: OverallDecision
    baseline_litres: float
    water_input_source: str
    messages: dict[str, FarmerMessage] = Field(default_factory=dict)


class SimulateRequest(WaterInput):
    farm_id: str
    scenarios: list[str] = Field(default_factory=list, max_length=10)
    custom: list[ScenarioParams] = Field(default_factory=list, max_length=5)
    weather_scenario: Optional[str] = None


class FieldPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    stage: Optional[Stage] = None
    soil_type: Optional[str] = None
    irrigation_method: Optional[str] = None
    soil_moisture_pct: Optional[float] = Field(default=None, ge=0, le=60)
    days_since_irrigation: Optional[int] = Field(default=None, ge=0, le=60)
    priority_override: Optional[float] = Field(default=None, ge=0.1, le=3.0)
    crop: Optional[str] = None


class FarmPatch(BaseModel):
    water_available_litres: Optional[float] = Field(default=None, ge=0, le=1e10)
    water_is_estimate: Optional[bool] = None
    water_source: Optional[str] = Field(default=None, max_length=40)


class FarmOverview(BaseModel):
    farm: Farm
    fields: list[Field_]
    result: Optional[PlanResult] = None
    recent_execution_ids: list[str] = []
    notes: list[str] = []
