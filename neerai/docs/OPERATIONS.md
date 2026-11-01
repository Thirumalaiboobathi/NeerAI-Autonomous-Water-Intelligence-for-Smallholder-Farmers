# Operations

Everything here describes the design; **no alarm, dashboard or log below has been observed in a live account yet.**

## Health
* `GET /health/live` — process is up (no dependencies).
* `GET /health/ready` — repository reachable (a DynamoDB `GetItem`). **Never** fails because Open-Meteo or Bedrock is down.
* `GET /api/health` — mode flags (`env`, `agent_mode`, `weather_provider`, `auth_mode`), no secrets.
* `python scripts/smoke_test.py <ApiUrl> [--token ...]` — post-deploy checks (PASS/FAIL/SKIP, exit code).

## Observability
* **Logs**: JSON, one object per line, with `request_id` (taken from `X-Request-ID` or generated; copied into the job and the SQS message so API and worker lines share one id). Retention 14 days (dev) / 30 days (prod). API Gateway access logs in their own group.
* **Metrics** (CloudWatch Embedded Metric Format, namespace `NeerAI`): `JobSucceeded`, `JobFailed`, `JobAttemptFailed`, `JobDurationMs`, `AgentFallbacks`, `JobMessageDropped`. Per-job record also stores steps, fallbacks, duration and mode.
* **Tracing**: no X-Ray/OpenTelemetry yet (not implemented); correlation ids are the substitute. Add `aws-xray-sdk` + `Tracing.ACTIVE` if needed.
* **Dashboard** `NeerAI-<stage>`: API Lambda, worker Lambda, queue/DLQ, agent job metrics, HTTP API.
* **Alarms** (all notify the SNS topic `AlarmTopicArn`; subscribe an email via `-c alertEmail=`, then confirm the subscription email): API/worker Lambda errors and throttles, worker p95 duration > 90 s, queue depth >= 10, oldest message > 10 min, **DLQ not empty**, API 5xx, DynamoDB read/write throttles, `JobFailed` >= 2 in 5 min, Bedrock server errors/throttles (dimension unconfirmed).

## Runbooks
**Jobs stuck / queue growing** — check worker errors and throttles; Bedrock latency (`JobDurationMs`); lower/raise `workerConcurrency`. Jobs older than the visibility window are retried automatically.
**DLQ not empty** — read a message (`aws sqs receive-message`): it holds ids only. Inspect the job (`pk=USER#<owner>, sk=job#<id>`); typical causes are a Bedrock outage or a code bug. After the fix, redrive from the SQS console ("Start DLQ redrive"). Redrive is safe: processing is idempotent.
**Bedrock failing/throttling** — the agent loop falls back to the deterministic engine per step (traced as `fallback`), so users still get correct numbers; persistent failures show as `AgentFallbacks`. Check model access and quotas in the Bedrock console; reduce concurrency.
**Weather provider down** — in `openmeteo` mode answers say "weather unavailable" and ask the farmer to retry; nothing is substituted. Switch the stage to `-c weatherProvider=auto` only if labelled simulated fallback is acceptable.
**Auth failures spike** — API Gateway access log `authError`; check token expiry/clock, the app client id in Amplify env vars, or Cognito domain.
**Cold starts** — the first request after idle can take several seconds (Strands imports). Provisioned concurrency would remove it at a fixed cost.

## Scaling
Lambda scales per request; the worker is capped by the event source max concurrency (default 3). DynamoDB on-demand. API Gateway throttle 20 rps/burst 40 is the intended demo ceiling; raise in `app.py` for real traffic.

## Demo reset
Per-user demo data: `POST /api/demo/load?key=madurai&reset=true` (affects only the caller's synthetic farms). Jobs/executions expire (jobs 7 days).

## Rollback
See [DEPLOYMENT](DEPLOYMENT.md#rollback).
