# Submission checklist

Only items that were actually verified are ticked. Last verification: 2026-10-31 (Windows 11, Python 3.13, Node 24).

## Verified
- [x] Original agent: orchestrator + 7 specialist Strands agents with deterministic tools (docs/ARCHITECTURE.md).
- [x] Working app in offline demo mode: `python scripts/demo.py`; all 8 pages rendered in a real browser (Tamil), no overflow at 390 px.
- [x] **Amazon Bedrock**: one real request succeeded with `apac.amazon.nova-pro-v1:0` in `ap-south-1` - 10 tool calls, 0 fallbacks, all checks passed (`scripts/validate_bedrock.py`). A second run (live weather) completed but hit a transient Bedrock `modelStreamErrorException` on the communication agent; the traced fallback finished it (64 s).
- [x] **Live weather**: Open-Meteo validated with real requests (5 gated tests, units/coords/horizon/ranges/freshness) and one full agent run on live data.
- [x] **CDK synthesis** succeeds (`aws-cdk-lib` 2.170); template audited for IAM, env, throttling, origins.
- [x] Lambda handler exercised with API Gateway v2 / Function URL event payloads (incl. origin-secret rejection).
- [x] Tests: backend 206 passed (+5 live); frontend 27 passed; `tsc -b` clean; `vite build` OK.

## Not verified - do not claim
- [ ] **Deployment**: nothing was deployed (no AWS costs incurred beyond two Bedrock runs). DynamoDB repository tested only against a stub table; Lambda zip build (`scripts/build_lambda.sh`) not run because the Docker daemon was not running.
- [ ] Workshop completion - author must confirm.
- [ ] Public GitHub repository - folder is not a git repo yet (see "Public repo preparation").
- [ ] Builder Center article published; link added.
- [ ] Demo video recorded (<3:00) and public; link added.
- [ ] Fresh-clone install test on a second machine.

## Screenshots
`docs/screenshots/dashboard-tamil.jpg`, `docs/screenshots/mobile-390px-dashboard-ask-planner.jpg`. Still to capture for the article: Scarcity, Simulator, Ask + timeline in English.

## Public repo preparation
```
cd neerai && git init && git add -A && git status        # confirm no .env, *.db, node_modules, cdk.out, backend/build
git commit -m "NeerAI: multi-agent irrigation decision support" && git branch -M main
git remote add origin <your-repo-url> && git push -u origin main   # then set visibility to Public
```
Before pushing: `git grep -nE "AKIA|aws_secret|originVerifySecret=" ` must find nothing; `.gitignore` already excludes `.env`, DB files, build output and `cdk.out`.
