"""REST API. Heavy agent runs execute in a worker thread under a hard timeout; deterministic endpoints are fast."""
from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from ..agents import messages as farmer_messages
from ..calculations import reference as ref
from ..calculations import scenarios as sc
from ..calculations.pipeline import build_context, run_core
from ..calculations.units import to_litres
from ..core.auth import Principal, current_principal
from ..core.config import Settings
from ..integrations.weather import MOCK_SCENARIOS
from ..repositories.base import EXECUTION, FARM, FIELD, PLAN, SCENARIO, Store
from ..schemas.jobs import Job, JobRequest, JobView
from ..services import audit
from ..services import jobs as jobsvc
from ..schemas.domain import (
    AgentExecution, Farm, FarmCreate, Field_, FieldCreate, IrrigationPlanRecord, Language, ScenarioComparison, ScenarioRecord,
)
from ..services import demo_seed, impact, reports
from ..services.weather_service import WeatherService
from .schemas import (
    AssessRequest, ChatRequest, FarmOverview, FarmPatch, FieldPatch, PlanRequest, PlanResult, SimulateRequest,
)


@dataclass
class AppState:
    settings: Settings
    store: Store
    weather: WeatherService
    queue: Any = None
    verifier: Any = None
    principal: Optional[Principal] = None


def state(request: Request, principal: Principal = Depends(current_principal)) -> AppState:
    """Per-request state whose store is scoped to the authenticated user: other users' records are unreachable."""
    base: AppState = request.app.state.neerai
    return dataclasses.replace(base, store=base.store.scoped(principal.user_id), principal=principal)


def run_assessment(*args, **kwargs):
    """Lazy wrapper: the API Lambda never loads Strands in AWS (keeps cold start short); tests patch this name."""
    from ..agents.orchestrator import run_assessment as _run

    return _run(*args, **kwargs)


router = APIRouter(prefix="/api")


def _demo_cap(st: AppState, kind: str) -> None:
    """Demo mode only: the shared demo principal may store a bounded number of records of each kind (abuse/cost control)."""
    s = st.settings
    if s.auth_mode != "demo":
        return
    limit = {FARM: s.demo_max_farms, FIELD: s.demo_max_fields, PLAN: s.demo_max_plans, SCENARIO: s.demo_max_scenarios}[kind]
    if st.store.count(kind) >= limit:
        raise HTTPException(429, f"demo limit reached: at most {limit} {kind} records. Delete one or reload the demo farm.")


def _farm_or_404(st: AppState, farm_id: str) -> Farm:
    farm = st.store.get(FARM, farm_id, Farm)
    if not farm:
        raise HTTPException(404, f"farm '{farm_id}' not found")
    return farm


def _fields(st: AppState, farm_id: str) -> list[Field_]:
    return sorted(st.store.list(FIELD, Field_, parent=farm_id), key=lambda f: f.created_at)


def _litres(wi_value: Optional[float], unit: str) -> Optional[float]:
    return None if wi_value is None else to_litres(wi_value, "m3" if unit == "m3" else "l")


def _check_weather_scenario(name: Optional[str]) -> None:
    if name and name not in MOCK_SCENARIOS:
        raise HTTPException(422, f"unknown weather scenario '{name}'. Options: {', '.join(MOCK_SCENARIOS)}")


def _weather_or_503(st: AppState, lat: float, lon: float, scenario: Optional[str]):
    try:
        return st.weather.get(lat, lon, scenario)
    except ValueError:
        raise
    except Exception as e:  # provider/network failure: say so, never substitute silently
        raise HTTPException(503, f"Live weather provider unavailable ({type(e).__name__}). Simulated data is not substituted in live mode.") from e


def seed_demo(st: AppState, key: str, reset: bool = False) -> Farm:
    farm, fields = demo_seed.build_demo(key)
    existing = [f for f in st.store.list(FARM, Farm) if f.is_demo and f.farm_name == farm.farm_name]
    if existing and not reset:
        return existing[0]
    for e in existing:
        for f in _fields(st, e.id):
            st.store.delete(FIELD, f.id)
        st.store.delete(FARM, e.id)
    _demo_cap(st, FARM)
    st.store.save(FARM, farm)
    for f in fields:
        st.store.save(FIELD, f, parent=farm.id)
    return farm


# ───────────────────────── health & reference ─────────────────────────

health_router = APIRouter()


@router.get("/health")
def health(request: Request):
    st: AppState = request.app.state.neerai
    return {"status": "ok", "agent_mode": st.settings.agent_mode, "weather_provider": st.settings.weather_provider,
            "env": st.settings.env, "repository": st.settings.repository, "auth_mode": st.settings.auth_mode}


@health_router.get("/health/live")
def live():
    """Liveness: the process is up. Does not touch any dependency."""
    return {"status": "alive"}


@health_router.get("/health/ready")
def ready(request: Request, response: Response):
    """Readiness: required local dependencies only (the repository). Open-Meteo/Bedrock being down never fails readiness."""
    st: AppState = request.app.state.neerai
    try:
        st.store.repo.get_raw("health", "ping")
    except Exception as e:  # noqa: BLE001
        response.status_code = 503
        return {"status": "not_ready", "repository": type(e).__name__}
    return {"status": "ready", "repository": "ok"}


@router.get("/reference/options")
def options():
    return {
        "crops": [{"key": k, "name_en": v["name_en"], "name_ta": v["name_ta"], "critical_stages": v["critical_stages"]} for k, v in ref.crops().items()],
        "soils": [{"key": k, "name_en": v["name_en"], "name_ta": v["name_ta"]} for k, v in ref.soils().items()],
        "methods": [{"key": k, "name_en": v["name_en"], "name_ta": v["name_ta"], "efficiency": v["efficiency"]} for k, v in ref.methods().items()],
        "stages": ["initial", "development", "mid", "late"],
        "weather_scenarios": list(MOCK_SCENARIOS),
        "disclaimer": "Crop/soil parameters are sample FAO-56-based values for demonstration; validate locally.",
    }


# ───────────────────────── farms & fields ─────────────────────────

@router.get("/farms")
def list_farms(st: AppState = Depends(state)) -> list[Farm]:
    return sorted(st.store.list(FARM, Farm), key=lambda f: f.created_at)


@router.post("/farms", status_code=201)
def create_farm(body: FarmCreate, st: AppState = Depends(state)) -> Farm:
    _demo_cap(st, FARM)
    farm = Farm(**body.model_dump())
    st.store.save(FARM, farm)
    return farm


@router.get("/farms/{farm_id}")
def get_farm(farm_id: str, st: AppState = Depends(state)) -> dict:
    farm = _farm_or_404(st, farm_id)
    return {"farm": farm, "fields": _fields(st, farm_id)}


@router.patch("/farms/{farm_id}")
def patch_farm(farm_id: str, body: FarmPatch, st: AppState = Depends(state)) -> Farm:
    farm = _farm_or_404(st, farm_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(farm, k, v)
    st.store.save(FARM, farm)
    return farm


@router.delete("/farms/{farm_id}", status_code=204)
def delete_farm(farm_id: str, st: AppState = Depends(state)) -> None:
    _farm_or_404(st, farm_id)
    for f in _fields(st, farm_id):
        st.store.delete(FIELD, f.id)
    st.store.delete(FARM, farm_id)


@router.get("/fields")
def list_fields(farm_id: Optional[str] = None, st: AppState = Depends(state)) -> list[Field_]:
    if farm_id:
        return _fields(st, farm_id)
    return sorted(st.store.list(FIELD, Field_), key=lambda f: f.created_at)


@router.post("/fields", status_code=201)
def create_field(body: FieldCreate, st: AppState = Depends(state)) -> Field_:
    _farm_or_404(st, body.farm_id)
    try:
        ref.get_crop(body.crop)
        if body.soil_type:
            ref.get_soil(body.soil_type)
        if body.irrigation_method:
            ref.get_method(body.irrigation_method)
        field = demo_seed.field_from_create(body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    _demo_cap(st, FIELD)
    st.store.save(FIELD, field, parent=body.farm_id)
    return field


@router.patch("/fields/{field_id}")
def patch_field(field_id: str, body: FieldPatch, st: AppState = Depends(state)) -> Field_:
    field = st.store.get(FIELD, field_id, Field_)
    if not field:
        raise HTTPException(404, "field not found")
    data = body.model_dump(exclude_unset=True)
    try:
        if data.get("crop"):
            ref.get_crop(data["crop"].lower())
            data["crop"] = data["crop"].lower()
        if data.get("soil_type"):
            ref.get_soil(data["soil_type"])
        if data.get("irrigation_method"):
            ref.get_method(data["irrigation_method"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    for k, v in data.items():
        setattr(field, k, v)
    st.store.save(FIELD, field, parent=field.farm_id)
    return field


@router.delete("/fields/{field_id}", status_code=204)
def delete_field(field_id: str, st: AppState = Depends(state)) -> None:
    if not st.store.get(FIELD, field_id, Field_):
        raise HTTPException(404, "field not found")
    st.store.delete(FIELD, field_id)


# ───────────────────────── weather ─────────────────────────

@router.get("/weather/{field_id}")
def field_weather(field_id: str, weather_scenario: Optional[str] = None, st: AppState = Depends(state)):
    _check_weather_scenario(weather_scenario)
    field = st.store.get(FIELD, field_id, Field_)
    if not field:
        raise HTTPException(404, "field not found")
    farm = _farm_or_404(st, field.farm_id)
    return _weather_or_503(st, farm.latitude, farm.longitude, weather_scenario)


# ───────────────────────── deterministic planning ─────────────────────────

def _plan(st: AppState, farm: Farm, fields: list[Field_], req: PlanRequest | SimulateRequest) -> tuple[PlanResult, float]:
    _check_weather_scenario(req.weather_scenario)
    ctx = build_context(farm, fields)
    override = _litres(req.available_water, req.available_water_unit)
    avail = override if override is not None else farm.water_available_litres
    if not ctx.fields:
        raise HTTPException(422, "; ".join(ctx.blocking_missing) or "farm has no fields")
    if avail is None:
        raise HTTPException(422, "available water volume is required")
    w = _weather_or_503(st, farm.latitude, farm.longitude, req.weather_scenario)
    overrides = getattr(req, "priority_overrides", None)
    r = run_core(ctx, w, avail, st.settings.planning_horizon_days, overrides)
    result = PlanResult(
        context=ctx, weather=w, crop_water=r.crop_water, allocation=r.allocation, decision=r.decision,
        baseline_litres=round(sum(n.baseline_volume_litres for n in r.crop_water.fields)),
        water_input_source="farmer-adjusted value" if override is not None else "farm profile estimate",
        messages={lg.value: farmer_messages.compose(r.decision, w, r.allocation, lg) for lg in Language},
    )
    return result, avail


@router.post("/irrigation/plan")
def irrigation_plan(body: PlanRequest, st: AppState = Depends(state)) -> PlanResult:
    farm = _farm_or_404(st, body.farm_id)
    result, avail = _plan(st, farm, _fields(st, farm.id), body)
    if body.save:
        _demo_cap(st, PLAN)
        rec = IrrigationPlanRecord(
            farm_id=farm.id, label=body.label or "Saved plan", available_litres=avail,
            total_demand_litres=result.allocation.total_demand_litres, total_allocated_litres=result.allocation.total_allocated_litres,
            deficit_litres=result.allocation.deficit_litres, baseline_litres=result.baseline_litres, decision=result.decision,
            allocation=result.allocation, weather_source=result.weather.source, weather_simulated=result.weather.simulated,
        )
        st.store.save(PLAN, rec, parent=farm.id)
        audit.record(st.store, "plan_saved", rec.id)
        result.plan_id = rec.id
    return result


@router.post("/water/allocate")
def water_allocate(body: PlanRequest, st: AppState = Depends(state)) -> PlanResult:
    """Water-scarcity allocation: same deterministic engine, tuned for what-if water volumes and farmer priorities."""
    return irrigation_plan(body, st)


@router.get("/irrigation/plans")
def list_plans(farm_id: Optional[str] = None, st: AppState = Depends(state)) -> list[IrrigationPlanRecord]:
    return st.store.list(PLAN, IrrigationPlanRecord, parent=farm_id)


@router.get("/irrigation/plans/{plan_id}/report", response_class=PlainTextResponse)
def plan_report(plan_id: str, st: AppState = Depends(state)) -> str:
    rec = st.store.get(PLAN, plan_id, IrrigationPlanRecord)
    if not rec:
        raise HTTPException(404, "plan not found")
    return reports.plan_markdown(rec)


@router.post("/irrigation/report", response_class=PlainTextResponse)
def adhoc_report(body: PlanRequest, st: AppState = Depends(state)) -> str:
    """Render a report for the current (unsaved) plan so the planner can export what is on screen."""
    farm = _farm_or_404(st, body.farm_id)
    result, avail = _plan(st, farm, _fields(st, farm.id), body)
    rec = IrrigationPlanRecord(
        farm_id=farm.id, label=body.label or "Current plan", available_litres=avail,
        total_demand_litres=result.allocation.total_demand_litres, total_allocated_litres=result.allocation.total_allocated_litres,
        deficit_litres=result.allocation.deficit_litres, baseline_litres=result.baseline_litres, decision=result.decision,
        allocation=result.allocation, weather_source=result.weather.source, weather_simulated=result.weather.simulated,
    )
    return reports.plan_markdown(rec)


@router.get("/farms/{farm_id}/overview")
def farm_overview(farm_id: str, weather_scenario: Optional[str] = None, st: AppState = Depends(state)) -> FarmOverview:
    farm = _farm_or_404(st, farm_id)
    fields = _fields(st, farm_id)
    recent = [e.id for e in st.store.list(EXECUTION, AgentExecution, parent=farm_id, limit=5)]
    notes: list[str] = []
    result = None
    if fields:
        try:
            result, _ = _plan(st, farm, fields, PlanRequest(farm_id=farm_id, weather_scenario=weather_scenario))
        except HTTPException as e:
            notes.append(str(e.detail))
    else:
        notes.append("No fields yet. Add a field to get an irrigation plan.")
    return FarmOverview(farm=farm, fields=fields, result=result, recent_execution_ids=recent, notes=notes)


# ───────────────────────── scenarios ─────────────────────────

@router.get("/scenarios/presets")
def presets():
    return [{"name": p.name, "title": p.title, "description": p.description} for p in sc.PRESETS.values()]


@router.post("/scenarios/simulate")
def simulate(body: SimulateRequest, st: AppState = Depends(state)) -> ScenarioComparison:
    farm = _farm_or_404(st, body.farm_id)
    _check_weather_scenario(body.weather_scenario)
    ctx = build_context(farm, _fields(st, farm.id))
    avail = _litres(body.available_water, body.available_water_unit)
    avail = avail if avail is not None else farm.water_available_litres
    if not ctx.fields or avail is None:
        raise HTTPException(422, "farm needs at least one field and an available water volume")
    params = []
    for n in body.scenarios:
        if n not in sc.PRESETS:
            raise HTTPException(422, f"unknown scenario '{n}'. Options: {', '.join(sc.PRESETS)}")
        params.append(sc.PRESETS[n])
    params += body.custom
    if not params:
        raise HTTPException(422, "choose at least one scenario or provide custom parameters")
    try:
        w = _weather_or_503(st, farm.latitude, farm.longitude, body.weather_scenario)
        comp = sc.compare(ctx, w, avail, params, st.settings.planning_horizon_days)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    _demo_cap(st, SCENARIO)
    st.store.save(SCENARIO, ScenarioRecord(farm_id=farm.id, comparison=comp), parent=farm.id)
    return comp


# ───────────────────────── agents ─────────────────────────

async def _run_agents(st: AppState, farm: Farm, query: str, language: Language, **kw) -> AgentExecution:
    if st.settings.env == "aws":
        raise HTTPException(410, "synchronous agent runs are disabled in this deployment; use POST /api/jobs and poll GET /api/jobs/{id}")
    fields = _fields(st, farm.id)
    try:
        ex = await asyncio.wait_for(
            asyncio.to_thread(run_assessment, farm, fields, query, language, settings=st.settings,
                              weather_fetcher=lambda lat, lon, d, _sc=kw.get("weather_scenario"): st.weather.get(lat, lon, _sc, d), **kw),
            timeout=st.settings.agent_timeout_s,
        )
    except asyncio.TimeoutError as e:
        raise HTTPException(504, f"agent workflow exceeded {st.settings.agent_timeout_s:.0f}s timeout") from e
    st.store.save(EXECUTION, ex, parent=farm.id)
    return ex


@router.post("/irrigation/assess")
async def assess(body: AssessRequest, st: AppState = Depends(state)) -> AgentExecution:
    farm = _farm_or_404(st, body.farm_id)
    _check_weather_scenario(body.weather_scenario)
    return await _run_agents(
        st, farm, body.query, body.language, available_litres=_litres(body.available_water, body.available_water_unit),
        priority_overrides=body.priority_overrides, weather_scenario=body.weather_scenario,
    )


@router.post("/agent/chat")
async def chat(body: ChatRequest, st: AppState = Depends(state)) -> AgentExecution:
    farm = _farm_or_404(st, body.farm_id)
    _check_weather_scenario(body.weather_scenario)
    return await _run_agents(st, farm, body.message, body.language, weather_scenario=body.weather_scenario)


# ───────────────────────── async jobs ─────────────────────────

class JobCreate(BaseModel):
    kind: Literal["assess", "chat"] = "assess"
    farm_id: str
    query: str = Field(min_length=1, max_length=500)
    language: Language = Language.en
    available_water: Optional[float] = Field(default=None, ge=0, le=1e10)
    available_water_unit: Literal["litres", "m3"] = "litres"
    priority_overrides: dict[str, float] = Field(default_factory=dict)
    weather_scenario: Optional[str] = None


@router.post("/jobs", status_code=202)
def create_job(body: JobCreate, response: Response, st: AppState = Depends(state),
               idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")) -> JobView:
    """Queue a long-running agent workflow. Poll GET /api/jobs/{id}; send an Idempotency-Key to make retries safe."""
    _check_weather_scenario(body.weather_scenario)
    if len(body.priority_overrides) > 20:
        raise HTTPException(422, "too many priority overrides")
    req = JobRequest(kind=body.kind, farm_id=body.farm_id, query=body.query, language=body.language,
                     available_litres=_litres(body.available_water, body.available_water_unit),
                     priority_overrides=body.priority_overrides, weather_scenario=body.weather_scenario)
    try:
        job, created = jobsvc.submit(st.settings, st.store, st.queue, req, idempotency_key)
    except KeyError as e:
        raise HTTPException(404, "farm not found") from e
    except jobsvc.QuotaExceeded as e:
        raise HTTPException(429, str(e), headers={"Retry-After": "30"}) from e
    except jobsvc.EnqueueFailed as e:
        raise HTTPException(503, "could not queue the job; please retry") from e
    if not created:
        response.status_code = 200
    return JobView.of(job)


@router.get("/jobs/{job_id}")
def get_job(job_id: str, st: AppState = Depends(state)) -> JobView:
    job = st.store.get("job", job_id, Job)
    if not job:
        raise HTTPException(404, "job not found")
    return JobView.of(job)


@router.get("/jobs")
def list_jobs(limit: int = Query(10, ge=1, le=50), st: AppState = Depends(state)) -> list[JobView]:
    return [JobView.of(j) for j in st.store.list("job", Job, limit=limit)]


@router.get("/agent/executions/{execution_id}")
def get_execution(execution_id: str, st: AppState = Depends(state)) -> AgentExecution:
    ex = st.store.get(EXECUTION, execution_id, AgentExecution)
    if not ex:
        raise HTTPException(404, "execution not found")
    return ex


@router.get("/agent/executions")
def list_executions(farm_id: Optional[str] = None, limit: int = Query(20, ge=1, le=100), st: AppState = Depends(state)) -> list[AgentExecution]:
    return st.store.list(EXECUTION, AgentExecution, parent=farm_id, limit=limit)


# ───────────────────────── impact & demo ─────────────────────────

@router.get("/impact/summary")
def impact_summary(st: AppState = Depends(state)):
    return impact.summarize(st.store)


@router.get("/demo/scenarios")
def demo_scenarios():
    seed = demo_seed.load_seed()
    return {
        "note": seed["_meta"]["note"], "farms": [{"key": f["key"], "name": f["farm"]["farm_name"], "district": f["farm"]["district"],
                                                    "fields": len(f["fields"])} for f in seed["farms"]],
        "weather_scenarios": [{"key": k, "description": d} for k, d in {
            "uncertain_rain": "Uncertain rain: 60% chance of 12 mm on day 2",
            "heatwave": "Simulated heatwave: 40-42 C, high ET0",
            "dry": "Dry spell: no rain",
            "heavy_rain": "Heavy rain: 28 mm and 35 mm on days 1-2"}.items()],
        "chat_examples": seed["chat_examples"],
        "what_if_presets": [{"name": p.name, "title": p.title} for p in sc.PRESETS.values()],
    }


@router.post("/demo/load", status_code=201)
def demo_load(key: str = "madurai", reset: bool = False, st: AppState = Depends(state)) -> Farm:
    try:
        return seed_demo(st, key, reset)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
