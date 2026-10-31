import type { AgentExecution, Farm, FarmOverview, FieldRec, Options, PlanResult, ScenarioComparison } from '../types/api'

export const farm: Farm = {
  id: 'farm_1', farmer_name: 'Murugan (demo)', farm_name: 'Sample farm - Melur', village: 'Sample village', district: 'Madurai',
  latitude: 10.03, longitude: 78.33, water_source: 'borewell', water_available_litres: 700000, water_is_estimate: true, is_demo: true, created_at: '2026-01-01T00:00:00Z',
}

export const fields: FieldRec[] = [
  { id: 'f1', farm_id: 'farm_1', name: 'Paddy plot', area_ha: 1, crop: 'paddy', stage: 'development', soil_type: 'clay_loam', irrigation_method: 'flood', priority_override: 1 },
  { id: 'f2', farm_id: 'farm_1', name: 'Groundnut plot', area_ha: 0.6, crop: 'groundnut', stage: 'mid', soil_type: 'red_sandy_loam', irrigation_method: 'furrow', priority_override: 1 },
]

export const options: Options = {
  crops: [{ key: 'paddy', name_en: 'Paddy (rice)', name_ta: 'நெல்' }, { key: 'groundnut', name_en: 'Groundnut', name_ta: 'நிலக்கடலை' }],
  soils: [{ key: 'clay_loam', name_en: 'Clay loam', name_ta: 'களிமண்' }, { key: 'red_sandy_loam', name_en: 'Red sandy loam', name_ta: 'செம்மண்' }],
  methods: [{ key: 'flood', name_en: 'Flood', name_ta: 'வாய்க்கால்', efficiency: 0.65 }, { key: 'furrow', name_en: 'Furrow', name_ta: 'சால்', efficiency: 0.6 }],
  stages: ['initial', 'development', 'mid', 'late'], weather_scenarios: ['uncertain_rain', 'heatwave'], disclaimer: 'sample',
}

const decision = (id: string, name: string, crop: string, action: 'PRIORITIZE_FIELD' | 'PARTIAL_IRRIGATION', litres: number) => ({
  field_id: id, field_name: name, crop, action, reasoning: [`reason for ${name}`], recommended_depth_mm: 50, recommended_volume_litres: litres,
  timing: 'Irrigate today', weather_considerations: ['Rain chance next 48h: 60%'], crop_stage_considerations: ['critical stage'], confidence: 'medium' as const,
  assumptions: ['Kc 1.15 x ET0 5 mm/day'], would_change_if: ['Rain arrives'],
})

export const plan: PlanResult = {
  context: { farm_id: 'farm_1', fields: [], missing_inputs: [], blocking_missing: [], water_available_litres: 700000 },
  weather: {
    horizon_days: 3, daily: [{ date: '2026-01-01', tmax_c: 34, tmin_c: 25, precip_mm: 0, precip_prob_pct: 15, et0_mm: 5.2 }, { date: '2026-01-02', tmax_c: 33, tmin_c: 25, precip_mm: 12, precip_prob_pct: 60, et0_mm: 4.6 }],
    rain_probability_48h_pct: 60, expected_rain_48h_mm: 7.2, expected_rain_horizon_mm: 8, avg_et0_mm_day: 4.9, max_temp_c: 34, heat_risk: 'none',
    forecast_confidence: 'low', source: 'NeerAI deterministic sample weather (SIMULATED)', simulated: true, fetched_at: '2026-01-01T06:00:00Z', notes: ['SIMULATED weather: not a live observation or forecast.'],
  },
  crop_water: {
    fields: [
      { field_id: 'f1', name: 'Paddy plot', crop: 'paddy', stage: 'development', area_ha: 1, kc: 1.1, et0_mm_day: 4.9, etc_mm_day: 5.4, taw_mm: 50, raw_mm: 20, depletion_mm: 24.6, depletion_source: 'estimated', effective_rain_mm: 4, net_requirement_mm: 43, gross_requirement_mm: 66, volume_litres: 661538, efficiency: 0.65, stress_now: true, due: true, defer_for_rain: false, rain_covers: false, critical_stage: true, stress_ratio: 1.2, baseline_volume_litres: 900000, assumptions: [] },
      { field_id: 'f2', name: 'Groundnut plot', crop: 'groundnut', stage: 'mid', area_ha: 0.6, kc: 1.15, et0_mm_day: 4.9, etc_mm_day: 5.6, taw_mm: 50, raw_mm: 25, depletion_mm: 45, depletion_source: 'measured', effective_rain_mm: 2, net_requirement_mm: 50, gross_requirement_mm: 83, volume_litres: 500000, efficiency: 0.6, stress_now: true, due: true, defer_for_rain: false, rain_covers: false, critical_stage: true, stress_ratio: 1.8, baseline_volume_litres: 400000, assumptions: [] },
    ],
    total_demand_litres: 1161538, total_due_demand_litres: 1161538, method: 'FAO-56',
  },
  allocation: {
    available_litres: 700000, total_demand_litres: 1161538, total_allocated_litres: 700000, deficit_litres: 461538, scarcity_mode: true, method: 'Priority tiers',
    notes: [],
    allocations: [
      { field_id: 'f2', name: 'Groundnut plot', crop: 'groundnut', demand_litres: 500000, allocated_litres: 500000, unmet_litres: 0, fraction_met: 1, rank: 1, score: 4.18, tier: 'critical', rationale: ['Crop is in a water-critical growth stage.'] },
      { field_id: 'f1', name: 'Paddy plot', crop: 'paddy', demand_litres: 661538, allocated_litres: 200000, unmet_litres: 461538, fraction_met: 0.3, rank: 2, score: 3.23, tier: 'critical', rationale: ['Receives 30% of its demand because water is limited.'] },
    ],
  },
  decision: {
    headline_action: 'PRIORITIZE_FIELD', summary: 'Irrigate 2 field(s)', total_recommended_litres: 700000, available_litres: 700000, scarcity_mode: true,
    decisions: [decision('f2', 'Groundnut plot', 'groundnut', 'PRIORITIZE_FIELD', 500000), decision('f1', 'Paddy plot', 'paddy', 'PARTIAL_IRRIGATION', 200000)],
    validation: ['PASS'], requires_farmer_approval: true,
  },
  baseline_litres: 1300000, water_input_source: 'farm profile estimate',
  messages: {
    en: { language: 'en', headline: 'Water is short: demand 1,161,538 L, available 700,000 L.', steps: ['Groundnut field: Irrigate this field first - about 500,000 L (83 mm).', 'This is a recommendation only; you make the final decision.'], short_summary: 's', voice_text: 'v' },
    ta: { language: 'ta', headline: 'தண்ணீர் பற்றாக்குறை: தேவை 1,161,538 லிட்டர், கிடைப்பது 700,000 லிட்டர்.', steps: ['நிலக்கடலை வயல்: முதலில் இந்த வயலுக்கு நீர் பாய்ச்சவும் - 500,000 லிட்டர் (83 மிமீ).', 'இது ஒரு பரிந்துரை மட்டுமே; இறுதி முடிவை நீங்களே எடுக்கவும்.'], short_summary: 's', voice_text: 'v' },
  },
}

export const overview: FarmOverview = { farm, fields, result: plan, recent_execution_ids: [], notes: [] }

export const execution: AgentExecution = {
  id: 'exec_1', farm_id: 'farm_1', query: 'I have only 400 m3 of water. Which field should I prioritize?', language: 'en', intent: 'scarcity_allocation', mode: 'demo', status: 'completed',
  created_at: '2026-01-01T06:00:00Z', duration_ms: 150,
  steps: [
    { seq: 1, agent: 'Orchestrator', tool: 'farm_context_specialist', kind: 'agent', status: 'ok', started_at: '2026-01-01T06:00:00Z', duration_ms: 20, summary: 'Farm Context Agent completed' },
    { seq: 2, agent: 'Farm Context Agent', tool: 'load_farm_context', kind: 'tool', status: 'ok', started_at: '2026-01-01T06:00:00Z', duration_ms: 2, summary: '2 field(s)' },
    { seq: 3, agent: 'Water Budget & Allocation Agent', tool: 'allocate_water_budget', kind: 'tool', status: 'ok', started_at: '2026-01-01T06:00:00Z', duration_ms: 3, summary: 'SCARCITY: allocated 400,000 of 400,000 L' },
  ],
  decision: plan.decision, allocation: plan.allocation, weather: plan.weather, message: plan.messages.en,
  answer: 'Water is short: demand 1,161,538 L, available 400,000 L. Groundnut field: Irrigate partially - about 400,000 L (67 mm).',
  data_sources: ['Weather: sample - SIMULATED'], follow_up_questions: ['What happens if I delay irrigation by one day?'], errors: [],
}

const sr = (name: string, demand: number, alloc: number, deficit: number) => ({
  name, title: name, description: '', hypothetical: name !== 'normal', total_demand_litres: demand, total_allocated_litres: alloc, deficit_litres: deficit,
  rainfall_contribution_mm: 2, available_litres: 700000, at_risk_fields: deficit > 0 ? ['Paddy plot'] : [],
  actions: { 'Paddy plot': name === 'custom' ? ('DELAY_AND_MONITOR' as const) : ('PARTIAL_IRRIGATION' as const), 'Groundnut plot': 'PRIORITIZE_FIELD' as const }, field_allocations: {}, delta_vs_base: {},
})
export const comparison: ScenarioComparison = {
  base: sr('normal', 1161538, 700000, 461538), scenarios: [sr('custom', 800000, 700000, 100000)], changed_actions: {},
  disclaimer: 'Scenario weather and water values are hypothetical inputs, not forecasts.',
}
