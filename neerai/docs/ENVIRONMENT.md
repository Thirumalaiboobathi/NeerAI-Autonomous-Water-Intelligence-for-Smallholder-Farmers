# Environment variable reference

Backend settings use the `NEERAI_` prefix (`neerai/.env.example` lists all of them with placeholders). Frontend variables are build-time `VITE_*` and **public** — never put secrets in them.

## Backend (Lambda environment is set by CDK)
| Variable | Local default | AWS value | Notes |
|---|---|---|---|
| `NEERAI_ENV` | `local` | `aws` | `aws` enables fail-fast validation (below) and disables docs and the sync agent routes |
| `NEERAI_AGENT_MODE` | `demo` | `bedrock` | demo = scripted Strands model, no AWS needed |
| `NEERAI_BEDROCK_MODEL_ID` / `_REGION` | `apac.amazon.nova-pro-v1:0` / `ap-south-1` | same | configurable |
| `NEERAI_BEDROCK_MAX_ATTEMPTS` | 3 | 3 | botocore standard mode = exponential backoff + jitter |
| `NEERAI_WEATHER_PROVIDER` | `mock` | `openmeteo` (CDK context `weatherProvider`) | must be set explicitly in `aws` env |
| `NEERAI_REPOSITORY` / `_DYNAMODB_TABLE` / `_AWS_REGION` | `sql` | `dynamodb` / table name / region | |
| `NEERAI_AUTH_MODE`, `_COGNITO_REGION`, `_COGNITO_USER_POOL_ID`, `_COGNITO_CLIENT_ID` | `none` | `cognito` + ids | |
| `NEERAI_QUEUE_BACKEND`, `_JOBS_QUEUE_URL` | `inline` | `sqs` + url | inline runs jobs in a local thread |
| `NEERAI_JOB_TIMEOUT_S`, `_JOB_MAX_ATTEMPTS`, `_JOB_TTL_DAYS` | 100, 3, 7 | same | keep job timeout < worker Lambda timeout (120 s) < queue visibility (180 s) |
| `NEERAI_MAX_ACTIVE_JOBS_PER_USER`, `_MAX_JOBS_PER_USER_PER_DAY` | 2, 40 | same | cost control |
| `NEERAI_CORS_ORIGINS` | localhost:5173 | Amplify origin | no `*`/localhost in `aws` env |
| `NEERAI_MAX_BODY_BYTES` | 65536 | same | 413 above |
| `NEERAI_LOG_LEVEL`, `NEERAI_LOG_FORMAT` | `INFO`, `text` | `INFO`, `json` | |
| `NEERAI_AUTO_SEED` | `true` | `false` | demo farms are loaded per user via `/api/demo/load` |

**Startup validation (`NEERAI_ENV=aws`)** raises `ConfigError` listing every problem: demo agents, SQL storage, inline queue, missing table/queue url, anonymous access, missing Cognito ids, localhost/wildcard CORS, auto-seed, or an unset weather provider.

## Frontend (Amplify environment variables)
`VITE_API_URL` (CDK output `ApiUrl`), `VITE_COGNITO_DOMAIN` (`CognitoDomain`), `VITE_COGNITO_CLIENT_ID` (`UserPoolClientId`). If the Cognito pair is unset, the app runs without sign-in (local demo).

## CDK context
`stage`, `frontendOrigin` (required), `weatherProvider`, `workerConcurrency`, `alertEmail`, `extraCallbackUrls`, `createBudget`, `budgetEmail`, `allowOtherRegion`.

## GitHub (per environment `dev`/`prod`, variables not secrets)
`AWS_ACCOUNT_ID`, `FRONTEND_ORIGIN`, `ALERT_EMAIL`. (The deploy role ARN is derived: `neerai-github-deploy-<stage>`.)
