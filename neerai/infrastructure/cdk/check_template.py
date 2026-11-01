#!/usr/bin/env python3
"""Static policy checks on a synthesized CloudFormation template (no AWS access needed). Exit 1 on any violation."""
import json
import sys

t = json.load(open(sys.argv[1], encoding="utf-8"))
R = t["Resources"]
bad: list[str] = []


def of(type_: str):
    return [(k, v["Properties"] if "Properties" in v else {}) for k, v in R.items() if v["Type"] == type_]


for k, p in of("AWS::IAM::Policy") + of("AWS::IAM::ManagedPolicy"):
    for s in p["PolicyDocument"]["Statement"]:
        acts = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
        res = s.get("Resource")
        res = res if isinstance(res, list) else [res]
        if any(a == "*" or a.endswith(":*") for a in acts):
            bad.append(f"{k}: wildcard action {acts}")
        if any(r == "*" for r in res):
            bad.append(f"{k}: wildcard resource for {acts}")
for k, p in of("AWS::Lambda::Url"):
    bad.append(f"{k}: Lambda Function URL (public) is not expected")
for k, p in of("AWS::DynamoDB::Table"):
    if not p.get("PointInTimeRecoverySpecification", {}).get("PointInTimeRecoveryEnabled"):
        bad.append(f"{k}: PITR off")
    if not p.get("TimeToLiveSpecification", {}).get("Enabled"):
        bad.append(f"{k}: TTL off")
for k, p in of("AWS::SQS::Queue"):
    if not p.get("SqsManagedSseEnabled") and not p.get("KmsMasterKeyId"):
        bad.append(f"{k}: queue not encrypted")
for k, p in of("AWS::Lambda::Function"):
    if p.get("Timeout", 3) > 120:
        bad.append(f"{k}: timeout above 120 s")
    if not p.get("LoggingConfig", {}).get("LogGroup"):
        bad.append(f"{k}: no explicit log group (unbounded retention)")
for k, p in of("AWS::Logs::LogGroup"):
    if "RetentionInDays" not in p:
        bad.append(f"{k}: log retention not set")
for k, p in of("AWS::ApiGatewayV2::Stage"):
    if "DefaultRouteSettings" not in p:
        bad.append(f"{k}: no default throttling")
    for rk, rs in p.get("RouteSettings", {}).items():
        if not set(rs) <= {"ThrottlingBurstLimit", "ThrottlingRateLimit", "LoggingLevel", "DetailedMetricsEnabled", "DataTraceEnabled"}:
            bad.append(f"{k}: route {rk} has property names CloudFormation will reject: {sorted(rs)}")
    if set(p.get("AccessLogSettings", {})) != {"DestinationArn", "Format"}:
        bad.append(f"{k}: access log settings missing or malformed")
auth_none = [p["RouteKey"] for _, p in of("AWS::ApiGatewayV2::Route") if p.get("AuthorizationType") == "NONE"]
allowed = {"GET /health/live", "GET /health/ready", "GET /api/health", "GET /api/reference/options", "GET /api/demo/scenarios"}
if set(auth_none) - allowed:
    bad.append(f"unexpected unauthenticated routes: {sorted(set(auth_none) - allowed)}")
if not any(p.get("AuthorizationType") == "JWT" for _, p in of("AWS::ApiGatewayV2::Route")):
    bad.append("no JWT-protected route")
for k, p in of("AWS::Cognito::UserPoolClient"):
    if p.get("GenerateSecret"):
        bad.append(f"{k}: public SPA client must not have a secret")
for k, p in of("AWS::ApiGatewayV2::Api"):
    origins = p.get("CorsConfiguration", {}).get("AllowOrigins", [])
    if not origins or "*" in origins:
        bad.append(f"{k}: CORS must be an explicit allow-list")
if bad:
    print("TEMPLATE CHECKS FAILED:\n  " + "\n  ".join(bad))
    sys.exit(1)
print(f"template checks passed ({len(R)} resources)")
