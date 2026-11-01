# Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Lambda init fails with `invalid production configuration: ...` | `NEERAI_ENV=aws` safety checks | the message lists each missing/unsafe variable; fix the CDK context/env |
| `Pass -c frontendOrigin=...` when running CDK | Amplify app not created yet | create it first (docs/DEPLOYMENT.md prerequisites) |
| Browser: CORS error | Amplify origin differs from `frontendOrigin` (preview branches, custom domain) | redeploy with the right `frontendOrigin` / `extraCallbackUrls` |
| Sign-in loops or "redirect_mismatch" | Cognito callback URL != site origin | the callback is `frontendOrigin + "/"`; update context and redeploy |
| 401 on every call after sign-in | `VITE_COGNITO_CLIENT_ID` belongs to another pool, or token expired | rebuild Amplify with the stack outputs; sign in again |
| 403 from API Gateway `Forbidden` | route not defined / wrong path | public routes are explicit; everything else needs a JWT |
| `POST /api/jobs` 429 | per-user quota or API throttle | wait for running jobs (limit 2) or the daily cap (40) |
| Job stays `queued` | worker throttled/erroring, or Bedrock slow | check worker alarms, `Errors`/`Throttles`, event source mapping state |
| Job `failed` with `agent_error` | 3 attempts failed (Bedrock, timeout) | read worker logs by `request_id`; check Bedrock access to `apac.amazon.nova-pro-v1:0` |
| `AccessDeniedException` invoking Bedrock | model access not enabled, or profile ARN mismatch | enable Nova Pro in the Bedrock console (ap-south-1); policy covers the profile and `foundation-model/amazon.nova-pro-v1:0` in any region |
| Answer says weather unavailable | live mode and Open-Meteo unreachable | retry; or deploy with `weatherProvider=auto` for a *labelled* simulated fallback |
| `build_lambda.py` refuses to run | not on Linux | use the CI workflow, or `--stub` for synth only |
| Package too large (>240 MB) | dependency growth | remove unused deps or move heavy ones to a Lambda layer |
| `cdk synth` needs an account | account used for ARNs | set `CDK_DEFAULT_ACCOUNT` (CI uses a placeholder, never deploys) |
| Deploy workflow fails at "Verify target account" | `AWS_ACCOUNT_ID` variable differs from the role's account | fix the variable; this check protects against deploying to the wrong account |
| Amplify build fails on Node version | default image Node too old | `amplify.yml` runs `nvm install 22`; keep it |
| SPA deep links 404 on Amplify | rewrite rule missing | add `frontend/amplify-redirects.json` rule in the console |
