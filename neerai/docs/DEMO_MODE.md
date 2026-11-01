# No-sign-in demo mode (dev stage only)

For hackathon demos the dev API can run **without Cognito sign-in**. It is off by default and impossible for prod.

## Switch
* CDK context `demoMode=true` (GitHub **dev** environment variable `DEMO_MODE=true`). Any value other than `true`, `false` or empty aborts synthesis.
* The stack then sets `NEERAI_AUTH_MODE=demo` and `NEERAI_STAGE=dev` on both Lambdas and attaches **no** JWT authorizer, so every route is open.
* Unset `DEMO_MODE` (or `false`) and redeploy to return to Cognito; the authorizer and protected routes come back. Nothing demo-specific persists.

## Dev-only guards (any one blocks prod)
1. `app.py`: `demoMode=true` with `stage=prod` exits at synthesis.
2. `Settings.validate_runtime`: `auth_mode=demo` requires `NEERAI_STAGE=dev`, job quotas <= 2 active / 30 per day and body <= 16 KB, else the Lambda refuses to start.
3. `check_template.py`: derives the mode from the synthesized Lambda environment and fails on demo + prod, loose throttles/quotas, or a mixed authorizer; Cognito mode still requires JWT on `POST /api/jobs` and `$default`.
4. CI synthesizes both modes and requires prod + demo to be rejected; the deploy workflow checks the exact template it is about to diff/deploy.

## Identity and data
Every request acts as the fixed principal `demo-public` (Cognito `sub` values are UUIDs, so it cannot collide with a real user). `Authorization`, `X-User-Id` and body fields such as `user_id` are ignored. Storage keys include the owner, so real users' records are unreachable.

## Limitations (accepted for a demo)
* **One shared tenant:** all visitors see, edit and delete the same farms, plans and jobs. Do not enter personal data.
* Caps: 10 rps / burst 20 API-wide, `POST /api/jobs` 1 rps / burst 2, 2 active and 30 agent jobs per day **in total**, 16 KB bodies, 5 farms / 30 fields / 50 plans / 50 scenarios (HTTP 429 beyond). Cap checks are count-then-write, so a burst can overshoot slightly.
* Throttles are global, not per IP (needs WAF); one abuser can exhaust them. The 30/day job cap is what bounds Bedrock spend.
* Body-size limit relies on the Content-Length header; field limits bound the rest.
* Agent execution records have no TTL (at most 30 per day).
* Unauthenticated requests can trigger live Open-Meteo lookups.
* Synchronous `/api/agent/chat` and `/api/irrigation/assess` stay disabled (410) in AWS; agent work goes through `POST /api/jobs`.

## Frontend
Sign-in is shown only when `VITE_COGNITO_DOMAIN` and `VITE_COGNITO_CLIENT_ID` are both set at build time. For demo mode leave them unset (keep `VITE_API_URL`). Cognito mode needs both.
