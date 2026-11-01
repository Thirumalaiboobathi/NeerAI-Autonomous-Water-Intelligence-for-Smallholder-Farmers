#!/usr/bin/env python3
"""Build the Lambda ZIP asset directory (Docker-free): backend/build/lambda = Linux dependencies + app + demo data.

  python scripts/build_lambda.py            # on a Linux x86_64 host (GitHub Actions ubuntu runner): real build
  python scripts/build_lambda.py --stub     # app code only, NO dependencies: just enough for `cdk synth` on any OS

Dependencies are installed as pre-built wheels for the Lambda runtime (Python 3.12, x86_64, glibc 2.28+), never compiled,
so the result does not depend on the build host's glibc. A pure-Python or missing wheel makes pip fail loudly.
Cross-building from Windows/macOS is not supported (some transitive deps carry OS-specific markers); use the CI workflow.
CDK zips the directory itself. Lambda limit: 250 MB unzipped (this script fails above 240 MB).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "backend" / "build" / "lambda"
LIMIT_MB = 240


def size_mb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e6


def main() -> int:
    stub = "--stub" in sys.argv
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    if not stub:
        if sys.platform != "linux":
            print("Refusing a real build on a non-Linux host (wheel/marker mismatch). Use the GitHub Actions workflow, or --stub for synth.")
            return 2
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "backend" / "requirements.txt"), "--target", str(OUT),
             "--only-binary=:all:", "--platform", "manylinux2014_x86_64", "--platform", "manylinux_2_28_x86_64",
             "--python-version", "3.12", "--implementation", "cp", "--abi", "cp312", "--no-cache-dir", "--upgrade"],
            check=True,
        )
    shutil.copytree(ROOT / "backend" / "app", OUT / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (OUT / "data").mkdir()
    shutil.copytree(ROOT / "data" / "demo", OUT / "data" / "demo")
    for pat in ("__pycache__", "tests", "test"):
        for d in OUT.rglob(pat):
            if d.is_dir() and d.parent != OUT / "app":
                shutil.rmtree(d, ignore_errors=True)
    mb = size_mb(OUT)
    print(f"{'STUB ' if stub else ''}package: {OUT}  unzipped {mb:.0f} MB (Lambda limit 250 MB)")
    if mb > LIMIT_MB:
        print("Package too large: drop unused dependencies, or move heavy ones into a Lambda layer.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
