export type Lang = 'en' | 'ta'
export type Stage = 'initial' | 'development' | 'mid' | 'late'
export type Action = 'IRRIGATE_NOW' | 'DELAY_AND_MONITOR' | 'PARTIAL_IRRIGATION' | 'PRIORITIZE_FIELD' | 'INSUFFICIENT_DATA'
export type Confidence = 'low' | 'medium' | 'high'

export interface Farm {
  id: string
  farmer_name: string
  farm_name: string
  village: string
  district: string
  latitude: number
  longitude: number
  water_source: string
  water_available_litres: number | null
  water_is_estimate: boolean
  is_demo: boolean
  created_at: string
}

export interface FieldRec {
  id: string
  farm_id: string
  name: string
  area_ha: number
  crop: string
  variety?: string | null
  sowing_date?: string | null
  stage: Stage
  soil_type?: string | null
  irrigation_method?: string | null
  soil_moisture_pct?: number | null
  days_since_irrigation?: number | null
  priority_override: number
}

export interface FieldContext {
  field_id: string
  name: string
  crop: string
  crop_name_en: string
  crop_name_ta: string
  stage: Stage
  area_ha: number
  soil_type: string
  irrigation_method: string
  efficiency: number
  assumed: string[]
  priority_override: number
}

export interface FarmContext {
  farm_id: string
  fields: FieldContext[]
  missing_inputs: string[]
  blocking_missing: string[]
  water_available_litres: number | null
}

export interface DailyWeather {
  date: string
  tmax_c: number
  tmin_c: number
  precip_mm: number
  precip_prob_pct: number
  et0_mm: number
}

export interface WeatherAssessment {
  horizon_days: number
  daily: DailyWeather[]
  rain_probability_48h_pct: number
  expected_rain_48h_mm: number
  expected_rain_horizon_mm: number
  avg_et0_mm_day: number
  max_temp_c: number
  heat_risk: 'none' | 'moderate' | 'high'
  forecast_confidence: Confidence
  source: string
  simulated: boolean
  fetched_at: string
  scenario?: string | null
  notes: string[]
}

export interface FieldWaterNeed {
  field_id: string
  name: string
  crop: string
  stage: Stage
  area_ha: number
  kc: number
  et0_mm_day: number
  etc_mm_day: number
  taw_mm: number
  raw_mm: number
  depletion_mm: number
  depletion_source: string
  effective_rain_mm: number
  net_requirement_mm: number
  gross_requirement_mm: number
  volume_litres: number
  efficiency: number
  stress_now: boolean
  due: boolean
  defer_for_rain: boolean
  rain_covers: boolean
  critical_stage: boolean
  stress_ratio: number
  baseline_volume_litres: number
  assumptions: string[]
}

export interface CropWaterAssessment {
  fields: FieldWaterNeed[]
  total_demand_litres: number
  total_due_demand_litres: number
  method: string
}

export interface FieldAllocation {
  field_id: string
  name: string
  crop: string
  demand_litres: number
  allocated_litres: number
  unmet_litres: number
  fraction_met: number
  rank: number
  score: number
  tier: 'critical' | 'standard' | 'deferred'
  rationale: string[]
}

export interface WaterAllocationPlan {
  available_litres: number
  total_demand_litres: number
  total_allocated_litres: number
  deficit_litres: number
  scarcity_mode: boolean
  allocations: FieldAllocation[]
  method: string
  notes: string[]
}

export interface IrrigationDecision {
  field_id: string
  field_name: string
  crop: string
  action: Action
  reasoning: string[]
  recommended_depth_mm: number
  recommended_volume_litres: number
  timing: string
  weather_considerations: string[]
  crop_stage_considerations: string[]
  confidence: Confidence
  assumptions: string[]
  would_change_if: string[]
}

export interface OverallDecision {
  headline_action: Action
  summary: string
  total_recommended_litres: number
  available_litres: number
  scarcity_mode: boolean
  decisions: IrrigationDecision[]
  validation: string[]
  requires_farmer_approval: boolean
}

export interface FarmerMessage {
  language: Lang
  headline: string
  steps: string[]
  short_summary: string
  voice_text: string
}

export interface PlanResult {
  plan_id?: string | null
  context: FarmContext
  weather: WeatherAssessment
  crop_water: CropWaterAssessment
  allocation: WaterAllocationPlan
  decision: OverallDecision
  baseline_litres: number
  water_input_source: string
  messages: Record<Lang, FarmerMessage>
}

export interface FarmOverview {
  farm: Farm
  fields: FieldRec[]
  result: PlanResult | null
  recent_execution_ids: string[]
  notes: string[]
}

export interface TraceStep {
  seq: number
  agent: string
  tool: string | null
  kind: 'agent' | 'tool' | 'fallback' | 'validation'
  status: 'ok' | 'error' | 'fallback'
  started_at: string
  duration_ms: number
  summary: string
}

export interface ScenarioResult {
  name: string
  title: string
  description: string
  hypothetical: boolean
  total_demand_litres: number
  total_allocated_litres: number
  deficit_litres: number
  rainfall_contribution_mm: number
  available_litres: number
  at_risk_fields: string[]
  actions: Record<string, Action>
  field_allocations: Record<string, number>
  delta_vs_base: Record<string, number>
}

export interface ScenarioComparison {
  base: ScenarioResult
  scenarios: ScenarioResult[]
  changed_actions: Record<string, Record<string, string>>
  disclaimer: string
}

export interface AgentExecution {
  id: string
  farm_id?: string
  query: string
  language: Lang
  intent: string
  mode: string
  status: 'completed' | 'partial' | 'failed'
  created_at: string
  duration_ms: number
  steps: TraceStep[]
  context?: FarmContext | null
  weather?: WeatherAssessment | null
  crop_water?: CropWaterAssessment | null
  allocation?: WaterAllocationPlan | null
  decision?: OverallDecision | null
  scenarios?: ScenarioComparison | null
  message?: FarmerMessage | null
  answer: string
  data_sources: string[]
  follow_up_questions: string[]
  errors: string[]
}

export interface ScenarioParams {
  name: string
  title: string
  description?: string
  water_factor?: number
  rainfall_mm?: number | null
  rain_probability_pct?: number | null
  temperature_delta_c?: number
  efficiency_override?: number | null
  area_factor?: number
  delay_days?: number
  priority_overrides?: Record<string, number>
}

export interface SavingsBlock {
  label: string
  litres: number
  kind: 'estimated_potential' | 'simulated' | 'measured'
  note: string
}

export interface ImpactSummary {
  farms: number
  fields_supported: number
  decisions_generated: number
  scenarios_evaluated: number
  latest_total_demand_litres: number
  latest_total_allocation_litres: number
  latest_water_deficit_litres: number
  cumulative_demand_litres: number
  cumulative_allocated_litres: number
  cumulative_deficit_litres: number
  baseline_definition: string
  savings: SavingsBlock[]
  additional_need_vs_baseline_litres: number
  by_farm: { farm_id: string; demand_litres: number; allocated_litres: number; deficit_litres: number; baseline_litres: number; need_litres: number }[]
}

export interface RefOption {
  key: string
  name_en: string
  name_ta: string
  efficiency?: number
  critical_stages?: Stage[]
}

export interface Options {
  crops: RefOption[]
  soils: RefOption[]
  methods: RefOption[]
  stages: Stage[]
  weather_scenarios: string[]
  disclaimer: string
}

export interface Health {
  status: string
  agent_mode: string
  weather_provider: string
  env: string
  repository: string
}

export interface PlanRequest {
  farm_id: string
  available_water?: number | null
  available_water_unit?: 'litres' | 'm3'
  priority_overrides?: Record<string, number>
  weather_scenario?: string | null
  save?: boolean
  label?: string
}

export interface FieldCreateBody {
  farm_id: string
  name: string
  area: number
  area_unit: 'ha' | 'acre'
  crop: string
  variety?: string | null
  sowing_date?: string | null
  stage: Stage
  soil_type?: string | null
  irrigation_method?: string | null
  soil_moisture_pct?: number | null
  days_since_irrigation?: number | null
}

export interface PlanRecordLite {
  id: string
  farm_id: string
  created_at: string
  label: string
  available_litres: number
  total_demand_litres: number
  total_allocated_litres: number
  deficit_litres: number
  baseline_litres: number
  weather_source: string
  weather_simulated: boolean
}
