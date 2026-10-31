# NeerAI: giving every drop of water a decision

*Draft for AWS Builder Center - Strands SDK: Workshop to Ship. Replace bracketed items before publishing.*

## The problem
Across Tamil Nadu, smallholder farmers decide when and how much to irrigate from habit, a fixed schedule, or a half-remembered forecast. The consequences are familiar: groundwater over-pumped on days when rain was coming, crops stressed in the weeks that matter most, and no principled way to choose which field gets water when a borewell runs short. Weather apps stop at the forecast. Farming chatbots stop at generic advice, usually not in the farmer's language, and an LLM asked "how many litres?" will happily invent an answer.

## What NeerAI does
NeerAI turns weather, crop stage, soil and the water actually available into a **decision with a reason**: irrigate now, delay and monitor, irrigate partially, or irrigate this field first. It answers in Tamil or English, shows its assumptions and uncertainty, and leaves the final call to the farmer. It never controls pumps.

Signature features: a **water scarcity mode** that ranks fields transparently and shows unmet demand; a **what-if simulator** (rain, heatwave, delay, drip, less water); and **Why this decision?** on every recommendation.

## How Strands Agents SDK is used
The core rule: *the model explains, tools calculate.*

* A `strands.Agent` **orchestrator** whose tools are seven specialist `strands.Agent`s (agents-as-tools): Farm Context, Weather Intelligence, Crop Water Intelligence, Water Budget & Allocation, Irrigation Decision, Scenario Simulation, and Tamil Farmer Communication.
* Each specialist owns deterministic `@tool` functions: FAO-56 crop water (ETc = Kc x ET0, root-zone depletion), unit conversion, a constrained priority allocator, and a scenario engine. Pydantic schemas type every agent output.
* A Strands `HookProvider` records every real tool call (name, duration, status, redacted summary) and uses `BeforeToolCallEvent.cancel_tool` to cap runaway loops. That trace is shown in the app.
* In AWS mode the model is Amazon Nova Pro through `BedrockModel`. For offline demos we wrote a small `strands.models.Model` subclass that emits tool-use events from a deterministic policy - the Strands event loop, tool registry and agent-to-agent delegation run for real, with no credentials.
* **Guardrails:** the LLM's narrative is accepted only if every quantity it states matches a tool result; otherwise a template built from verified numbers is used. If an agent step fails, a traced deterministic fallback completes it, and missing essentials (like "how much water do you have?") become questions rather than guesses.

## Why this is not a farming chatbot
A chatbot answers a question. NeerAI maintains a *farm model* (fields, crop stage, soil, water source, water on hand), pulls a forecast, runs agronomic calculations, and returns an action with volumes that provably fit the water budget. It asks for missing inputs instead of guessing, shows assumptions, and records a tool-level trace of how the answer was produced.

## How deterministic calculations keep numbers reliable
Crop water need uses FAO-56 (ETc = Kc x ET0), a root-zone depletion balance, probability-weighted effective rainfall and application efficiency; litres = area (ha) x depth (mm) x 10,000. The LLM routes and explains; it cannot change a number. We learned why the hard way during Bedrock validation: Nova Pro once skipped the tool that applies the farmer's stated "400 m3" and the plan silently used 700 m3. The orchestrator now enforces stated volumes deterministically, rejects model scratchpad text, and accepts an LLM narrative only if every quantity matches a tool result.

## How water-scarcity allocation works
Each due field gets a score = crop weight x stage factor (critical stage x2) x stress urgency x the farmer's own priority. Critical or pinned fields are funded first in rank order; the remaining water is shared by score (water-filling, capped at demand). The invariant "allocated never exceeds available" is property-tested, unmet demand is shown per field, and any priority change recomputes instantly.

## How Tamil accessibility improves inclusion
The whole UI, every recommendation and the action card are available in Tamil, with large touch targets, a 390 px mobile layout, and voice-ready text. Messages are generated from templates fed by verified numbers, so units, crop names and quantities are identical in Tamil and English (a test enforces that every English quantity appears in the Tamil message). Browser text-to-speech is optional and depends on installed voices.

## What is simulated versus live
Live: Open-Meteo forecasts (validated against the real API) and Amazon Bedrock inference. Simulated and always labelled "Simulated data": the demo weather scenarios (uncertain rain, heatwave, dry, heavy rain), the two sample farms, soil-moisture values and water volumes, and every what-if input (hypothetical). In live-weather mode, if the provider is down NeerAI says so rather than substituting simulated data.

## How the agents collaborate (example)
"I have only 400 m3. Which field first?" -> Context (converts to litres) -> Weather (labelled simulated, rain 60%, confidence low) -> Crop Water (paddy needs 662 m3, groundnut 500 m3) -> Budget (groundnut critical stage funded first) -> Decision (PRIORITIZE_FIELD, validated against the budget) -> Communication (Tamil steps with the same numbers).

## AWS services
Amazon Bedrock (inference), Lambda + API Gateway (FastAPI via Mangum), DynamoDB (documents), S3 (reports, static site), CloudFront (distribution), CloudWatch (logs and alarms), CDK (infrastructure as code). IAM is scoped to one model, one table and one bucket. The CDK stack synthesizes and its IAM was audited; [state clearly whether you deployed it]. One finding worth sharing: API Gateway's 30 s limit is shorter than a multi-agent Bedrock run, so long agent routes go through a Lambda Function URL behind CloudFront.

## How impact is measured - and what we do not claim
NeerAI reports three separate savings categories: *estimated potential* (modelled against an explicit fixed-schedule baseline), *simulated* (what-if), and *measured* (zero until farmers log water-meter data). We do not claim real savings we have not measured. Demo weather is clearly labelled simulated.

## What we learned
1. Put every number behind a tool, then test those tools like any other code: 206 backend tests (plus live-API tests) including a property test that allocation never exceeds the budget.
2. Tests found modelling bugs, not just code bugs (a "delay" scenario that lowered demand because it discarded a measured soil reading).
3. Honest uncertainty is a feature: low-confidence simulated weather visibly lowers recommendation confidence.

## Try it
`git clone [repo]`, `python scripts/demo.py`, open http://localhost:5173. Works offline in demo mode; set `NEERAI_AGENT_MODE=bedrock` to use Amazon Bedrock. Crop and soil parameters are sample FAO-56-based values - validate locally before real use.
