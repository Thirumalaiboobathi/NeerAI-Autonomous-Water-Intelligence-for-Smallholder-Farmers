"""Run ONE irrigation assessment through the real Strands + Amazon Bedrock path and check it.

Usage (from repo root):  backend/.venv/Scripts/python scripts/validate_bedrock.py [--query "..."] [--weather mock|auto|openmeteo]
Credentials come from the default AWS chain (profile/SSO/role); nothing is read from or written to code.
Costs: a single orchestrated request = a handful of Nova Pro calls (cents at most). Exit code 0 only if every check passes.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("NEERAI_AGENT_MODE", "bedrock")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", default="I have only 400 m3 of water. Which field should I prioritize?")
    ap.add_argument("--weather", default="mock", choices=["mock", "auto", "openmeteo"])
    ap.add_argument("--timeout", type=float, default=120)
    a = ap.parse_args()

    from app.agents import messages
    from app.agents.orchestrator import run_assessment
    from app.core.config import Settings
    from app.schemas.domain import Language
    from app.services.demo_seed import build_demo

    s = Settings(agent_mode="bedrock", weather_provider=a.weather, agent_timeout_s=a.timeout)
    print(f"region={s.bedrock_region} model={s.bedrock_model_id} weather={a.weather}")
    try:
        import boto3
        ident = boto3.client("sts", region_name=s.bedrock_region).get_caller_identity()["Arn"]
        print("caller:", ident.split(":")[-1])
    except Exception as e:  # noqa: BLE001
        print(f"BLOCKER: no usable AWS credentials ({type(e).__name__}). Configure a profile/SSO/role and retry.")
        return 2

    farm, fields = build_demo("madurai")
    t0 = time.perf_counter()
    ex = run_assessment(farm, fields, a.query, Language.en, settings=s)
    dt = time.perf_counter() - t0
    for st in ex.steps:
        print(f"{st.seq:>2} [{st.kind:10}] {st.status:8} {str(st.tool or st.agent)[:36]:36} {st.duration_ms:>6} ms  {st.summary[:70]}")
    print("\nANSWER:", ex.answer)

    fallbacks = [x for x in ex.steps if x.kind == "fallback"]
    guard = [x for x in ex.steps if x.tool == "number_guard"]
    llm_steps = [x for x in ex.steps if x.kind == "tool"]
    checks = {
        "completed": ex.status == "completed",
        "mode is bedrock": ex.mode == "bedrock",
        "all 5 core agents ran via LLM tool calls": {"farm_context_specialist", "weather_specialist", "crop_water_specialist",
                                                       "water_budget_specialist", "decision_specialist"} <= {x.tool for x in ex.steps},
        "no deterministic fallback needed": not fallbacks,
        "budget respected": bool(ex.allocation) and ex.allocation.total_allocated_litres <= ex.allocation.available_litres + 1e-6,
        "stated water (400 m3) applied": bool(ex.allocation) and ex.allocation.available_litres == 400_000 if "400 m3" in a.query else True,
        "number guard ran": bool(guard),
        "answer quantities trace to tools": bool(ex.decision) and messages.numbers_consistent(
            ex.answer, messages.collect_numbers([ex.context, ex.weather, ex.crop_water, ex.allocation, ex.decision, ex.scenarios])),
        "weather labelled": bool(ex.weather) and (ex.weather.simulated == (a.weather == "mock") or a.weather != "mock"),
    }
    print(f"\n{len(llm_steps)} tool calls, {len(fallbacks)} fallbacks, {dt:.1f}s, errors={ex.errors}")
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    print(json.dumps({"verified_bedrock": all(checks.values()), "model": s.bedrock_model_id, "region": s.bedrock_region}))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
