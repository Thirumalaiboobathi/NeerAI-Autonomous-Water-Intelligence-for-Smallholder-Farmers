# NeerAI - Every drop has a decision

Autonomous water intelligence for smallholder farmers (Tamil Nadu focus). A multi-agent decision-support app built on the **Strands Agents SDK** and Amazon Bedrock that turns weather, crop stage, soil and the water actually available into an explainable irrigation plan in **Tamil or English**. It never controls pumps; the farmer approves every action.

## Why
Farmers irrigate by habit or fixed schedule: wasting groundwater before rain, stressing crops at critical stages, and lacking a principled way to share short water between fields. Weather apps give forecasts; chatbots give generic (and sometimes invented) numbers. NeerAI gives a decision, the evidence for it, and the uncertainty.

## Features
Dashboard ("What should I do today?") - My Farms with onboarding and map - Irrigation Planner (adjust water/priorities, compare, save, export) - **Water Scarcity mode** - **What-If Simulator** - Ask NeerAI (chat with trace) - Impact (estimated vs simulated vs measured, explicit baseline) - Tamil/English with voice-ready text and optional speech - "Why this decision?" on every recommendation - agent activity timeline.

## Architecture & agents
Orchestrator `strands.Agent` delegating to 7 specialist Agents (Farm Context, Weather, Crop Water, Water Budget, Decision, Scenario, Tamil Communication), each with deterministic tools. **LLMs never compute numbers.** Details and Mermaid diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Stack: Python 3.12+, Strands Agents 1.63, FastAPI, Pydantic, SQLAlchemy (SQLite/PostgreSQL) or DynamoDB - React, TypeScript, Vite, MUI, TanStack Query, Recharts, Leaflet - AWS CDK (Lambda, API Gateway, DynamoDB, S3, CloudFront, CloudWatch, Bedrock).

## Quick start (no AWS needed)
```
cd backend && python -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt   # Linux/Mac: .venv/bin/pip
cd ../frontend && npm install
cd .. && python scripts/demo.py        # UI http://localhost:5173, API docs http://localhost:8000/docs
```
Two sample farms (Madurai: paddy/groundnut/ragi; Theni: drip banana/tomato) are seeded on first start. Demo mode uses deterministic **simulated** weather (choose uncertain rain / heatwave / dry / heavy rain in Settings) and a scripted Strands model. Try: "I have only 400 m3 of water. Which field should I prioritize?"

`docker compose up --build` -> http://localhost:8080. Bedrock: `NEERAI_AGENT_MODE=bedrock` (see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).

## Validate the real integrations
```
backend/.venv/Scripts/python scripts/validate_bedrock.py                  # ONE real Bedrock assessment (cents). Needs AWS creds + Nova Pro access
backend/.venv/Scripts/python scripts/validate_bedrock.py --weather openmeteo   # with live weather
set NEERAI_LIVE_TESTS=1 && cd backend && python -m pytest tests/test_live_weather.py    # real Open-Meteo calls
cd infrastructure/cdk && python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
set CDK_CONTEXT_JSON={"originVerifySecret":"<random>"} && set CDK_OUTDIR=cdk.out && python app.py   # synthesize only; deploys nothing
```
In `ap-south-1` Nova Pro needs the inference profile `apac.amazon.nova-pro-v1:0` (the default). Required IAM: `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` on that profile and the underlying foundation model.

## Configuration
See [.env.example](.env.example) (all `NEERAI_*`). Key ones: `AGENT_MODE` (demo|bedrock), `BEDROCK_MODEL_ID`, `WEATHER_PROVIDER` (mock|openmeteo|auto), `DATABASE_URL`, `REPOSITORY` (sql|dynamodb), `AGENT_TIMEOUT_S`, `AGENT_MAX_TOOL_CALLS`, `CORS_ORIGINS`.

## Tests
```
cd backend && python -m pytest        # 206 tests: calculations, allocation property tests, agents, API, eval dataset
cd frontend && npm test && npm run typecheck
```
Evaluation dataset: `backend/tests/eval/scenarios.json` (tool use, water constraints, honesty, Tamil, recovery) - deterministic, no LLM judge.

## API
FastAPI docs at `/docs`: `/api/health`, `/api/farms`, `/api/fields`, `/api/weather/{field_id}`, `/api/irrigation/assess|plan`, `/api/water/allocate`, `/api/scenarios/simulate`, `/api/agent/chat`, `/api/agent/executions/{id}`, `/api/impact/summary`, `/api/demo/scenarios`.

## Limitations (please read)
- Crop coefficients, soil constants and effective-rain rules are **sample FAO-56-based values** in `backend/app/calculations/data/`; validate with local agronomists. Depletion without a soil-moisture reading is a rough estimate (stated as an assumption in every result).
- Demo weather is simulated. Live Open-Meteo is validated with real requests; in live mode (`NEERAI_WEATHER_PROVIDER=openmeteo`) an outage yields an explicit "weather unavailable" answer, never simulated data. `auto` mode is an opt-in labelled fallback.
- Bedrock mode is verified with real requests (see checklist). The DynamoDB repository and the deployed CDK stack are **not verified against a live AWS account**; CDK synthesis passes but nothing was deployed.
- Savings are modelled against a stated baseline; **measured savings are zero** until farmers log meter data.
- Bedrock run-to-run reliability: Nova Pro occasionally fails mid-stream or skips a tool call; NeerAI enforces required inputs deterministically and completes missing steps via a traced fallback (a request can then take 60 s+).
- Demand is capped at a full root-zone refill, so a heatwave does not raise demand for fields that are already fully depleted.
- Single-user, no authentication; in-memory rate limiting. Tamil text-to-speech depends on browser voices.

## Future work
Auth and farmer groups, soil-moisture sensor ingestion, meter-based measured savings, SMS/WhatsApp voice delivery, community water-sharing across farms, calibrated regional crop parameters, Bedrock Guardrails.

Docs: [Architecture](docs/ARCHITECTURE.md) - [Deployment](docs/DEPLOYMENT.md) - [Article draft](docs/BUILDER_CENTER_ARTICLE.md) - [Demo script](docs/DEMO_VIDEO_SCRIPT.md) - [Checklist](docs/SUBMISSION_CHECKLIST.md)
