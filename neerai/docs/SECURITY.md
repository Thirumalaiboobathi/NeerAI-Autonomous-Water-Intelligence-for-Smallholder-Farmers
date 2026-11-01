# Security

Scope: the serverless AWS deployment (not deployed yet; every control below is **implemented and tested locally or checked in the synthesized template**, none verified against live AWS unless stated).

## Controls
| Area | Control | Evidence |
|---|---|---|
| Authentication | Cognito user pool; PKCE hosted-UI flow, no client secret. API Gateway JWT authorizer **and** in-app verification (signature via JWKS, issuer, expiry, `token_use=access`, `client_id`) | `tests/test_aws_production.py` (expired, wrong issuer, wrong client, id token, wrong key, `alg=none`, missing sub); `check_template.py` |
| Public routes | Only `/health/live`, `/health/ready`, `/api/health`, `/api/reference/options`, `/api/demo/scenarios` | template check fails on any other unauthenticated route |
| Authorization / IDOR | Every record's storage key includes the verified token `sub` (`USER#<sub>` partition). A client-supplied id can only address the caller's own records; others return 404 | tenant-isolation tests for farms, fields, plans, jobs, executions, impact (SQL and DynamoDB/moto) |
| Input validation | Pydantic limits (query 500 chars, water volumes, overrides <= 20), 64 KB body cap, unknown weather scenarios rejected | tests |
| Optional no-sign-in demo (dev only) | `demoMode=true` is refused for prod by CDK, Lambda startup validation and the template check; one shared principal, hard caps. See [DEMO_MODE.md](DEMO_MODE.md) | `tests/test_demo_mode.py`, `check_template.py` |
| Rate limiting | API Gateway stage throttle 20 rps/burst 40, `POST /api/jobs` 3/6; per-user: 2 active jobs, 40 jobs/day; worker max concurrency caps Bedrock load. The in-process limiter is local-only | template check; quota test |
| CORS | Explicit allow-list (the Amplify origin); startup fails on `*`/localhost in `aws` env | config tests |
| IAM | API Lambda: DynamoDB Get/Put/Delete/Query on one table, SQS send on one queue. Worker: same DynamoDB, SQS receive/delete/visibility on one queue, Bedrock invoke on one model + one inference profile. **No `*` actions; the only wildcard is the region in the foundation-model ARN** (a cross-region APAC profile may route to several regions) | `check_template.py`, audited template |
| Secrets | None needed; none stored. Cognito ids/API URL are public. No keys in frontend, source or outputs | design; `git grep` check in checklist |
| Data at rest | DynamoDB AWS-managed KMS key, PITR; SQS SSE; S3 not used | template |
| Data in transit | HTTPS everywhere (API Gateway, Cognito, Amplify, Bedrock, Open-Meteo); SQS/SNS enforce SSL | template |
| Security headers | HSTS, CSP, X-Frame-Options DENY, nosniff, Referrer-Policy via `customHttp.yml`; API sends `nosniff`, `no-store` | file; **must be re-checked on the live Amplify site** |
| Logging / privacy | JSON logs with a redaction filter (keys, bearer tokens, emails, phones); no prompts or farm details logged; job records hold the question for <= 7 days (TTL); audit trail stores ids/actions only (90 days) | tests |
| Fail-fast config | `NEERAI_ENV=aws` refuses demo mode, SQL storage, inline queue, anonymous access, implicit weather provider, auto-seed | 11 config tests |
| Errors | Generic 500 / safe job messages; `/docs` and OpenAPI disabled in `aws` env | tests |

## Threat model (summary)
| Threat | Mitigation | Residual risk |
|---|---|---|
| Authentication bypass / forged token | two independent verifications; algorithm pinned to RS256 | JWKS fetched over the internet at cold start; an outage blocks new containers' first auth |
| Cross-user access | owner is part of the DynamoDB key; no scans in request paths | owner derivation depends on the verified `sub` only |
| Prompt injection / tool misuse | the LLM can only call fixed, typed tools; all numbers come from deterministic code; output guard rejects unverified quantities; farm ids are validated against the caller's records; tool-call cap per run | a malicious question can still make the *explanation* odd; decisions/volumes stay tool-derived |
| Bedrock cost abuse | auth required, throttles, per-user job quotas, bounded retries (3 attempts), concurrency cap, 120 s timeout, budget + alarms | a determined authenticated user can still use ~40 runs/day; self-signup widens the user pool |
| Weather-provider failure | strict mode reports "unavailable"; no silent simulated substitution; simulated data always labelled | forecast quality depends on Open-Meteo |
| Queue poisoning / replay | messages carry ids only; unknown/forged jobs dropped; terminal jobs ignored; deterministic execution ids; DLQ for poison | anyone with `sqs:SendMessage` on the queue (only the API role) could enqueue an id of an existing job - harmless because jobs are idempotent |
| Secret exposure | no secrets exist | token theft via XSS (sessionStorage) |
| Public data exposure | no S3 buckets; DynamoDB/SQS not public; no Lambda Function URLs (template check) | execute-api endpoint is public by design (authenticated) |

## Known limitations
* No WAF (cost). API Gateway throttling is the edge control; consider AWS WAF if abuse appears.
* No MFA, no advanced-security (cost); password policy is 10 chars with upper/lower/digit.
* Cognito default email sender is limited; account recovery relies on email.
* Bedrock CloudWatch alarm dimensions for the APAC profile are unconfirmed (they may stay in `INSUFFICIENT_DATA`; treated as not breaching).
* Decision support only: crop/soil parameters are sample FAO-56 values; NeerAI never controls pumps.
