#!/usr/bin/env python3
"""Post-deployment smoke test (stdlib only). Usage:
  python scripts/smoke_test.py https://<api-id>.execute-api.ap-south-1.amazonaws.com [--token <cognito access token>]

Without a token it checks the public/unauthenticated surface only (a demo-mode dev API, auth_mode "demo", needs no token). With a token it also runs the real flow:
load demo farm -> submit agent job -> poll to a terminal state -> check the answer and weather labelling.
Exit code 0 only if every executed check passed; skipped checks are printed as SKIP, never as PASS.
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid


def call(base, method, path, token=None, body=None, headers=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw[:1] in "{[" else raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  - ' + str(detail)) if detail and not ok else ''}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base")
    ap.add_argument("--token")  # not needed in demo mode
    a = ap.parse_args()
    base = a.base.rstrip("/")

    s, b = call(base, "GET", "/health/live")
    check("liveness", s == 200 and b.get("status") == "alive", (s, b))
    s, b = call(base, "GET", "/health/ready")
    check("readiness (repository reachable)", s == 200 and b.get("status") == "ready", (s, b))
    s, b = call(base, "GET", "/api/health")
    mode = b.get("auth_mode") if isinstance(b, dict) else None
    check("api health reports aws env, bedrock, cognito or demo",
          s == 200 and b.get("env") == "aws" and b.get("agent_mode") == "bedrock" and mode in ("cognito", "demo"), (s, b))
    print(f"INFO  weather_provider={b.get('weather_provider') if isinstance(b, dict) else '?'}  auth_mode={mode}")
    demo = mode == "demo"
    if demo:
        print("WARN  auth_mode=demo: this API is UNAUTHENTICATED (dev demo only); the Cognito rejection checks do not apply")
    else:
        s, _ = call(base, "GET", "/api/farms")
        check("unauthenticated request rejected (401)", s == 401, s)
        s, _ = call(base, "GET", "/api/farms", token="not.a.valid.token")
        check("garbage token rejected (401)", s == 401, s)
        s, _ = call(base, "POST", "/api/jobs", body={"farm_id": "x", "query": "hi"})
        check("unauthenticated job submit rejected", s == 401, s)

    if not a.token and not demo:
        print("SKIP  authenticated flow (pass --token <access token>)")
    else:
        t = a.token  # None in demo mode: requests carry no Authorization header
        s, farm = call(base, "POST", "/api/demo/load?key=madurai", t, {})
        check("load synthetic demo farm", s in (200, 201) and "id" in farm, (s, farm))
        if s in (200, 201):
            s, farms = call(base, "GET", "/api/farms", t)
            check("farm list scoped to this user", s == 200 and any(f["id"] == farm["id"] for f in farms), s)
            s, plan = call(base, "POST", "/api/irrigation/plan", t,
                           {"farm_id": farm["id"], "available_water": 400, "available_water_unit": "m3"})
            check("deterministic plan respects water budget", s == 200 and plan["allocation"]["total_allocated_litres"] <= 400000 + 1, s)
            key = "smoke-" + uuid.uuid4().hex[:12]
            body = {"farm_id": farm["id"], "query": "I have only 400 m3. Which field first?", "language": "en"}
            s, job = call(base, "POST", "/api/jobs", t, body, {"Idempotency-Key": key})
            check("job accepted (202)", s == 202 and job.get("status") in ("queued", "running"), (s, job))
            s2, again = call(base, "POST", "/api/jobs", t, body, {"Idempotency-Key": key})
            check("idempotent resubmit returns same job", s2 == 200 and again.get("id") == job.get("id"), (s2, again))
            t0, status = time.time(), job
            while status.get("status") not in ("succeeded", "failed") and time.time() - t0 < 240:
                time.sleep(3)
                _, status = call(base, "GET", f"/api/jobs/{job['id']}", t)
            check("job reaches terminal state", status.get("status") in ("succeeded", "failed"), status)
            check("job succeeded", status.get("status") == "succeeded", status.get("error"))
            if status.get("status") == "succeeded":
                s, ex = call(base, "GET", f"/api/agent/executions/{status['execution_id']}", t)
                check("execution recorded with a decision", s == 200 and bool(ex.get("decision")), s)
                check("agent ran on Bedrock", ex.get("mode") == "bedrock", ex.get("mode"))
                w = ex.get("weather") or {}
                check("weather is explicitly labelled live or simulated", "simulated" in w and bool(w.get("source")), w.get("source"))
                fb = sum(1 for x in ex.get("steps", []) if x.get("kind") == "fallback")
                print(f"INFO  weather source: {w.get('source')} (simulated={w.get('simulated')}); fallback steps: {fb}")
    ok = all(results)
    print(f"\n{'ALL EXECUTED CHECKS PASSED' if ok else 'SMOKE TEST FAILED'} ({sum(results)}/{len(results)})")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
