#!/usr/bin/env bash
# Build the Lambda package (Linux deps + app + demo data) into backend/build using the official Lambda Python image.
# Requires a running Docker daemon. boto3/botocore are provided by the Lambda runtime and are removed to save space.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf backend/build && mkdir -p backend/build
docker run --rm --entrypoint /bin/bash -v "$PWD":/work -w /work public.ecr.aws/lambda/python:3.12 -c \
  "pip install -r backend/requirements.txt -t backend/build --no-cache-dir && rm -rf backend/build/boto3* backend/build/botocore* backend/build/s3transfer* backend/build/__pycache__"
cp -r backend/app backend/build/app
mkdir -p backend/build/data && cp -r data/demo backend/build/data/demo
du -sm backend/build | awk '{print "unzipped size (MB):", $1, "(Lambda limit 250)"}'
