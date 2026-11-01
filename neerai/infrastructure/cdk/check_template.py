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
    routes = {rp["RouteKey"]: rk for rk, rp in of("AWS::ApiGatewayV2::Route")}
    deps = R[k].get("DependsOn", [])
    deps = [deps] if isinstance(deps, str) else deps
    for rk in p.get("RouteSettings", {}):
        if rk not in routes:
            bad.append(f"{k}: RouteSettings key {rk!r} matches no route in the template")
        elif routes[rk] not in deps:
            bad.append(f"{k}: must DependOn route {routes[rk]} ({rk}) or API Gateway rejects the stage")
    if set(p.get("AccessLogSettings", {})) != {"DestinationArn", "Format"}:
        bad.append(f"{k}: access log settings missing or malformed")
# ── auth mode: derived from what the Lambdas will actually run with, never from a flag passed to this script ──
lam_env = [p.get("Environment", {}).get("Variables", {}) for _, p in of("AWS::Lambda::Function")]
modes = {e.get("NEERAI_AUTH_MODE") for e in lam_env if "NEERAI_AUTH_MODE" in e}
stages = {e.get("NEERAI_STAGE") for e in lam_env if "NEERAI_AUTH_MODE" in e}
if len(modes) != 1 or not modes <= {"cognito", "demo"}:
    bad.append(f"NEERAI_AUTH_MODE must be one of cognito/demo on every function, got {sorted(map(str, modes))}")
if len(stages) != 1 or not stages <= {"dev", "prod"}:
    bad.append(f"NEERAI_STAGE must be set to dev or prod on every function, got {sorted(map(str, stages))}")
demo = modes == {"demo"}
if demo and stages != {"dev"}:
    bad.append(f"DEMO MODE (no sign-in) is allowed only for the dev stage, got stage {sorted(map(str, stages))}")
if demo:
    # The shared demo principal has no per-user quota of its own, so these are global cost/abuse caps (keep in sync with app.py).
    e = lam_env[0]
    if int(e.get("NEERAI_MAX_ACTIVE_JOBS_PER_USER", 99)) > 2 or int(e.get("NEERAI_MAX_JOBS_PER_USER_PER_DAY", 999)) > 30:
        bad.append("demo mode: agent jobs must be capped at <=2 active and <=30 per day")
    if int(e.get("NEERAI_MAX_BODY_BYTES", 10**9)) > 16384:
        bad.append("demo mode: NEERAI_MAX_BODY_BYTES must be <= 16384")
    for k, p in of("AWS::ApiGatewayV2::Stage"):
        d = p.get("DefaultRouteSettings", {})
        if d.get("ThrottlingRateLimit", 10**9) > 10 or d.get("ThrottlingBurstLimit", 10**9) > 20:
            bad.append(f"{k}: demo mode default throttle must be <= 10 rps / burst 20")
        j = p.get("RouteSettings", {}).get("POST /api/jobs", {})
        if j.get("ThrottlingRateLimit", 10**9) > 1 or j.get("ThrottlingBurstLimit", 10**9) > 2:
            bad.append(f"{k}: demo mode POST /api/jobs throttle must be <= 1 rps / burst 2")
    if of("AWS::ApiGatewayV2::Authorizer"):
        bad.append("demo mode synthesized with a JWT authorizer attached: expected an open API (demo) - mixed config is unsafe")
auth_none = [p["RouteKey"] for _, p in of("AWS::ApiGatewayV2::Route") if p.get("AuthorizationType") == "NONE"]
allowed = {"GET /health/live", "GET /health/ready", "GET /api/health", "GET /api/reference/options", "GET /api/demo/scenarios",
           "OPTIONS /{proxy+}"}  # the OPTIONS catch-all lets CORS preflights (which carry no token) through
if not demo and set(auth_none) - allowed:
    bad.append(f"unexpected unauthenticated routes: {sorted(set(auth_none) - allowed)}")
route_auth = {p["RouteKey"]: p.get("AuthorizationType") for _, p in of("AWS::ApiGatewayV2::Route")}
if route_auth.get("OPTIONS /{proxy+}") != "NONE":
    bad.append("CORS preflight: OPTIONS /{proxy+} must exist and be unauthenticated, else browsers get 401 on preflight")
if demo:  # every route is intentionally open and acts as the single demo principal; Cognito-protected mode is checked below
    for rk in ("POST /api/jobs", "$default"):
        if route_auth.get(rk) != "NONE":
            bad.append(f"demo mode: route {rk!r} should be open (NONE); found {route_auth.get(rk)}")
else:
    for rk in ("POST /api/jobs", "$default"):
        if route_auth.get(rk) != "JWT":
            bad.append(f"route {rk!r} must stay JWT-protected")
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
print(f"template checks passed ({len(R)} resources, auth mode: {'DEMO - unauthenticated, dev only' if demo else 'cognito'})")
