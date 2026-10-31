# Deployment

> Status: `cdk` synthesis passes and the template was audited; **nothing has been deployed**. The Lambda zip build needs Docker (not run here). Deploying incurs AWS costs - get approval first.

## Local (no AWS)
```
cd backend && python -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt
cd frontend && npm install
python scripts/demo.py        # API :8000 (docs at /docs), UI :5173
```

## Docker Compose
`docker compose up --build` then open http://localhost:8080 (nginx proxies `/api` to the backend; demo mode, SQLite volume).

## Bedrock locally
Enable model access to Amazon Nova Pro in the Bedrock console (region `ap-south-1`, or set `NEERAI_BEDROCK_REGION`), configure credentials (`aws configure`/SSO), then `NEERAI_AGENT_MODE=bedrock`. If your region needs an inference profile, set `NEERAI_BEDROCK_MODEL_ID` accordingly.

## AWS (CDK)
Design notes (from validation): API Gateway HTTP APIs cap integrations at **30 s**, but a Bedrock multi-agent assessment measured 27-64 s. So CloudFront routes `/api/agent/*` and `/api/irrigation/assess` to a **Lambda Function URL** (60 s origin timeout) and everything else to API Gateway (throttled 20 rps). Both origins get a secret header (`x-origin-verify`) that the app checks, so direct access is rejected. Lambda uses the APAC inference profile, strict live weather, and least-privilege IAM (4 DynamoDB actions, `s3:PutObject` on reports, Bedrock on one profile/model).
```
bash scripts/build_lambda.sh                       # Linux deps + app + data into backend/build (needs Docker running)
cd frontend && npm ci && npm run build && cd ..
cd infrastructure/cdk && pip install -r requirements.txt
cdk synth  -c originVerifySecret=<random>=16+chars  # or: CDK_CONTEXT_JSON=... CDK_OUTDIR=cdk.out python app.py
cdk deploy -c originVerifySecret=<same>             # ONLY after cost approval
aws s3 sync ../../frontend/dist s3://<SiteBucket output> && aws cloudfront create-invalidation --distribution-id <DistributionId> --paths "/*"
```
Known limits: the secret is a plain Lambda env var (move to Secrets Manager for production); the in-app rate limiter sees CloudFront IPs (rely on API Gateway throttling); Bedrock model access must be enabled in the console; Lambda cold start with Strands imports is several seconds.
