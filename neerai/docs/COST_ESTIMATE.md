# Cost estimate (serverless design)

**These are estimates from published price structures I recalled; they were NOT checked against the live AWS price list or Cost Explorer, and I have not measured usage.** Verify at the AWS Pricing Calculator before approving. Region `ap-south-1`.

## Price check (AWS Price List API, read-only, run 2026-11-01)
Confirmed from the API: Amplify Hosting in Mumbai (build US$0.01/min, storage US$0.023/GB, data transfer out **US$0.15/GB**, hosting compute US$0.30/million requests); SQS standard US$0.40/million (first tier, other regions listed); Lambda requests ~US$0.20/million and GB-second US$0.0000166667 (rows returned were for other regions; Mumbai is normally the same tier but not individually confirmed); API Gateway HTTP US$1.00-1.23/million (Mumbai row not individually confirmed); CloudWatch standard alarm US$0.10/month.
**Not confirmed:** Bedrock Nova Pro token prices (the Price List API returned no rows), DynamoDB Mumbai on-demand rates, PITR storage rate, EMF custom-metric rate. Treat those figures below as assumptions.

## Fixed vs usage
| Service | Fixed (idle) charge | Usage-based |
|---|---|---|
| Lambda (API + worker) | none | per request + GB-second; free tier covers a demo |
| API Gateway HTTP API | none | ~US$1 per million requests |
| SQS | none | ~US$0.40 per million requests; first million free |
| DynamoDB on-demand | none (PITR adds a small per-GB storage charge) | per read/write unit; pennies at demo scale |
| Cognito | none | free tier of monthly active users; check current tier/limits |
| SNS | none | negligible |
| CloudWatch | **dashboard** (first 3 free per account, then ~US$3/mo each); **alarms** (14 here; first 10 free per account, then ~US$0.10/alarm/mo) | logs ingest ~US$0.50/GB; custom (EMF) metrics ~US$0.30/metric/mo |
| Amplify Hosting | none | build minutes, data served, storage (small for one SPA) |
| Bedrock Nova Pro | none | per input/output token; **the dominant variable cost** |
| **NAT Gateway, ALB, Fargate, WAF, CloudFront** | **not used (US$0)** | |

Expected idle total: **about US$0-3/month** (alarms/dashboard beyond the free allowance, if any). No resource bills hourly while idle.

## Bedrock (assumption-based)
One assessment = one orchestrator call plus up to ~7 specialist calls; assume ~15-30K input and ~2-4K output tokens per assessment (unmeasured; the real runs earlier took 27-64 s). At roughly US$0.8 per million input and US$3.2 per million output tokens (verify), that is on the order of **US$0.02-0.05 per assessment**. 40 assessments/day/user x N users is bounded by the per-user quota and worker concurrency. Deterministic features (plan, allocate, simulate) cost no Bedrock.

## Guardrails
* `-c createBudget=true -c budgetEmail=...` adds a **US$25/month** budget alert at 80% actual and 100% forecast (the budget is filtered on the `Project=NeerAI` tag; activate it as a cost-allocation tag in Billing first). Not created unless you choose it.
* Throttles + per-user quotas + max worker concurrency bound Bedrock spend; log retention 14/30 days; PITR is the only always-on storage extra.
* Post-deploy review: Cost Explorer filtered by `Project=NeerAI` after 1 and 7 days.

## Teardown
`cdk destroy` as described in [DEPLOYMENT](DEPLOYMENT.md#teardown). Retained: DynamoDB table and Cognito pool (small storage cost until you delete them).
